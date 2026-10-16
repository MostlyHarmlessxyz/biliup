// Included by benchmark.py's isolated crate, whose path modules are the real
// current native implementation and the hash-verified frozen C ABI bindings.
// Unsafe is confined to this benchmark's C reference/counter bridge; the native
// production module still compiles with its own forbid(unsafe_code).
use std::collections::BTreeMap;
use std::ffi::{CStr, CString, c_char, c_void};
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

unsafe extern "C" {
    fn benchmark_usage(user_us: *mut u64, system_us: *mut u64, peak_rss_bytes: *mut u64) -> i32;
    fn benchmark_c_core(
        input: *const c_char,
        output: *const c_char,
        options: *const frozen_sys::df_options,
        owned_pool: *mut *mut c_void,
        result: *mut frozen_sys::df_result,
    ) -> i32;
    fn benchmark_c_release(owned_pool: *mut c_void);
}

struct CPool(*mut c_void);
impl Drop for CPool {
    fn drop(&mut self) {
        // SAFETY: the bridge transfers ownership only after a successful core
        // call; it is released once, with the same frozen C implementation.
        unsafe { benchmark_c_release(self.0) }
    }
}

enum Retained {
    Native(native::layout::LayoutedPool),
    C(CPool),
}

#[derive(Clone, Copy)]
struct Snapshot {
    wall: Instant,
    user_us: u64,
    system_us: u64,
    peak_rss_bytes: u64,
    rusage_peak_rss_bytes: u64,
}

fn snapshot() -> io::Result<Snapshot> {
    let (mut user_us, mut system_us, mut peak_rss_bytes) = (0, 0, 0);
    // SAFETY: three valid output pointers are used only during this call.
    if unsafe { benchmark_usage(&mut user_us, &mut system_us, &mut peak_rss_bytes) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(Snapshot {
        wall: Instant::now(),
        user_us,
        system_us,
        // Linux getrusage can retain a pre-exec launch high-water floor.
        // Keep it as a separate observable; /proc reports this image's HWM.
        peak_rss_bytes: current_image_peak().unwrap_or(peak_rss_bytes),
        rusage_peak_rss_bytes: peak_rss_bytes,
    })
}

fn current_image_peak() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        let line = status.lines().find(|line| line.starts_with("VmHWM:"))?;
        return line
            .split_whitespace()
            .nth(1)?
            .parse::<u64>()
            .ok()?
            .checked_mul(1024);
    }
    #[cfg(not(target_os = "linux"))]
    None
}

fn profile(stage: &str, metadata: serde_json::Value) {
    if std::env::var_os("BILIUP_BENCH_PROFILE").is_none() {
        return;
    }
    let status = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let memory: Vec<_> = status
        .lines()
        .filter(|line| line.starts_with("VmRSS:") || line.starts_with("VmHWM:"))
        .collect();
    eprintln!(
        "{}",
        serde_json::json!({"stage":stage,"memory":memory,"metadata":metadata})
    );
}

fn delta(before: Snapshot, after: Snapshot) -> serde_json::Value {
    serde_json::json!({
        "wall_ms": after.wall.duration_since(before.wall).as_secs_f64() * 1000.0,
        "cpu_user_ms": (after.user_us - before.user_us) as f64 / 1000.0,
        "cpu_system_ms": (after.system_us - before.system_us) as f64 / 1000.0,
    })
}

fn c_path(path: &Path) -> Result<CString, Box<dyn std::error::Error>> {
    Ok(CString::new(path.as_os_str().as_encoded_bytes())?)
}

fn c_core(
    input: &Path,
    temporary: &Path,
    options: &ConvertOptions,
) -> Result<(Retained, ConvertStats), Box<dyn std::error::Error>> {
    let input = c_path(input)?;
    let output = c_path(temporary)?;
    let font = CString::new(options.font_name.as_str())?;
    let raw = frozen_sys::df_options {
        struct_size: std::mem::size_of::<frozen_sys::df_options>() as u32,
        resolution_x: options.width.try_into()?,
        resolution_y: options.height.try_into()?,
        display_area: options.display_area,
        scroll_area: options.scroll_area,
        scroll_time: options.scroll_time,
        fix_time: options.fix_time,
        density: options.density,
        line_spacing: options.line_spacing,
        top_margin: options.top_margin,
        bottom_margin: options.bottom_margin,
        font_size: options.font_size,
        font_size_strict: options.font_size_strict.into(),
        font_size_norm: options.font_size_norm.into(),
        font_name: font.as_ptr(),
        opacity: i32::from(options.opacity),
        outline: options.outline,
        outline_blur: options.outline_blur,
        outline_opacity: i32::from(options.outline_opacity),
        shadow: options.shadow,
        bold: options.bold.into(),
        save_blocked: options.save_blocked.into(),
        block_mode: options.block_mode.try_into()?,
    };
    let mut result = frozen_sys::df_result::new();
    let mut pool = std::ptr::null_mut();
    // SAFETY: borrowed paths/options stay valid for the call, result and pool
    // are valid outputs, and the successful pool is immediately owned by RAII.
    let status = unsafe {
        benchmark_c_core(
            input.as_ptr(),
            output.as_ptr(),
            &raw,
            &mut pool,
            &mut result,
        )
    };
    if status != frozen_sys::DF_OK {
        // SAFETY: the frozen fail() helper always terminates this message.
        let message = unsafe { CStr::from_ptr(result.message.as_ptr()) }.to_string_lossy();
        return Err(format!(
            "C reference status={status} code={} errno={}: {message}",
            result.upstream_code, result.os_error
        )
        .into());
    }
    Ok((
        Retained::C(CPool(pool)),
        ConvertStats {
            danmaku_count: result.danmaku_count.try_into()?,
            blocked_count: result.blocked_count.try_into()?,
        },
    ))
}

fn native_core(
    input: &Path,
    file: &mut File,
    options: &ConvertOptions,
) -> Result<(Retained, ConvertStats), Box<dyn std::error::Error>> {
    native::validate(options)?;
    let mut pool = native::parse::read_file(File::open(input)?, native::parse::Budget::RAW)?;
    if std::env::var_os("BILIUP_BENCH_PROFILE").is_some() {
        profile(
            "parsed",
            serde_json::json!({"count":pool.len(),"capacity":pool.capacity(),"source_size":std::mem::size_of::<native::model::Danmaku>(),"event_size":std::mem::size_of::<native::model::Danmaku>(),"text_length":pool.iter().map(|d|d.text.len()).sum::<usize>()}),
        );
    }
    native::model::normalize_and_sort(&mut pool, options);
    let events = native::layout::layout(pool, options)?;
    profile(
        "layout_complete",
        serde_json::json!({"count":events.len(),"capacity":events.capacity()}),
    );
    let stats = ConvertStats {
        danmaku_count: events.len().try_into()?,
        blocked_count: events
            .iter()
            .filter(|event| event.blocked().is_some())
            .count()
            .try_into()?,
    };
    let mut writer = BufWriter::new(file);
    native::writer::write(&mut writer, &events, options)?;
    writer.flush()?;
    let _original_handle = writer.into_inner().map_err(|error| error.into_error())?;
    profile("serialized", serde_json::json!({}));
    Ok((Retained::Native(events), stats))
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 4 {
        return Err(
            "usage: benchmark-driver native|c INPUT.xml NEW_OUTPUT.ass OPTIONS.json".into(),
        );
    }
    let engine = args[0].to_str().ok_or("engine is not UTF-8")?;
    let input = PathBuf::from(&args[1]);
    let output = PathBuf::from(&args[2]);
    let options: ConvertOptions = serde_json::from_slice(&std::fs::read(&args[3])?)?;
    if std::fs::symlink_metadata(&output).is_ok() {
        return Err("output already exists".into());
    }
    let parent = output
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let mut phases = BTreeMap::new();
    let initial = snapshot()?;
    let mut temporary = tempfile::Builder::new()
        .prefix(".biliup-benchmark-")
        .tempfile_in(parent)?;
    let before_core = snapshot()?;
    phases.insert("temporary_setup", delta(initial, before_core));
    let (retained, stats) = match engine {
        "native" => native_core(&input, temporary.as_file_mut(), &options)?,
        "c" => c_core(&input, temporary.path(), &options)?,
        _ => return Err("engine must be native or c".into()),
    };
    let after_core = snapshot()?;
    phases.insert("core", delta(before_core, after_core));
    temporary.as_file().sync_all()?;
    let after_sync = snapshot()?;
    phases.insert("sync", delta(after_core, after_sync));
    let file = temporary.persist_noclobber(&output)?;
    let after_publish = snapshot()?;
    phases.insert("publish", delta(after_sync, after_publish));
    phases.insert("end_to_end", delta(initial, after_publish));
    // Output inspection and hashing are deliberately outside core/E2E timing.
    let output_bytes = file.metadata()?.len();
    let before_cleanup = snapshot()?;
    drop(retained);
    drop(file);
    let after_cleanup = snapshot()?;
    phases.insert(
        "cleanup_memory_and_handles",
        delta(before_cleanup, after_cleanup),
    );
    let peak_rss_bytes = [
        initial,
        before_core,
        after_core,
        after_sync,
        after_publish,
        before_cleanup,
        after_cleanup,
    ]
    .iter()
    .map(|snapshot| snapshot.peak_rss_bytes)
    .max()
    .unwrap();
    let result = serde_json::json!({
        "schema": 1,
        "engine": engine,
        "stats": stats,
        "output_bytes": output_bytes,
        "peak_rss_bytes":peak_rss_bytes,
        "initial_peak_rss_bytes":initial.peak_rss_bytes,
        "rusage_peak_rss_bytes":after_cleanup.rusage_peak_rss_bytes,
        "phases": phases,
        "output_retained_for_external_hash_and_delete": true,
    });
    println!("{}", serde_json::to_string(&result)?);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("benchmark driver failed: {error}");
        std::process::exit(1);
    }
}
