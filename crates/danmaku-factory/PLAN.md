# DanmakuFactory → Rust 重构实施 Plan（最终修订稿）

## 1. 文档状态、基线与既定范围

**本文是本次重构的唯一主实施 Plan，已正式保存于 `crates/danmaku-factory/PLAN.md`。** 文档最初仅交付计划；2026-10-16 用户已另行授权连续实施 Gate 0–6。下文历史落盘记录保留，实际执行状态以第 9 节证据索引为准。

此前已搜索仓库中包含隐藏目录的计划类文档，没有找到上一轮方案的独立文件。因此将完整修订稿保存在负责实施的 crate 旁，避免与文档站用户教程混放；后续仅维护这一份实施计划。除补充预算膨胀证明、排序时间契约、`version()` 调用方兼容性检查，以及更新交付状态、源码链接和必要的一致性说明外，保留上一轮全部章节、技术决策、测试矩阵、Gate 和验收要求。

落盘前核对结果：

| 项目 | 已确认状态 |
|---|---|
| 当前分支 | `refactor/rust_danmaku` |
| 当前 HEAD | `76d03061053733d0c298677bf8ec22dac82263b8` |
| 工作区 | 创建本 Plan 前干净，无暂存或未暂存修改 |
| 历史参考 | `feature/moasic_live@acc4bdabfbbc0c71b8b71d0c3ab5ca6b7d74e84b` |
| 当前转换实现 | Rust 包装层调用 vendored C DanmakuFactory 和 PCRE2 |
| 现有 Golden | 30 个配置化样例 |
| 上轮配置检查 | `cargo metadata --locked --no-deps --format-version 1` 成功 |

以上是文档核对时的基线，正式开始 Gate 0 时必须重新检查实际 Git 状态，不能假设 HEAD 或工作区没有变化。

保留既有审计事实：仓库跟踪的转换相关 C/H 共 62 个文件、76,413 行，其中 PCRE2 占 67,957 行；历史移植引入约 95.9 万行 PCRE2 Rust 文件。该历史移植只作为局部算法参考，不整体合并或 cherry-pick。

以下决策保持不变：

- 在现有 `danmaku-factory` 中实现安全 Rust 核心，最终启用 `#![forbid(unsafe_code)]`。
- 范围限于 biliup 当前使用的转换能力，不引入平行业务 crate、完整 PCRE2、C ABI 或历史内存管理模型。
- 复用 `quick-xml` 0.37、工作区 Serde、`serde_json`、`thiserror`；文件事务使用仓库已有的 `tempfile` 依赖系列。当前锁文件解析为 `tempfile 3.27.0`。
- 正则需求出现时使用工作区 `regex`。当前转换范围不需要正则黑名单，不新增正则引擎。
- 不引入 YAML 解析依赖，不扩大至 FFmpeg、libass、SQLite、加密库或其他业务重构。
- 保持公共转换 API、配置、统计结果、worker JSON 结构及协议版本兼容。
- 主动修复已批准的排序、文本截断、UTF-8、实体解码和 Locale 行为。
- 保留 worker 的取消、超时和隔离能力。
- **C 参考实现冻结至最终退出 Gate，通过全部前置验收后才能删除。**

## 2. 接口、数据流与布局行为契约

### 2.1 公共接口与兼容适配

保持以下接口及其序列化形状：

- `convert_xml_to_ass(&Path, &Path, &ConvertOptions) -> Result<ConvertStats, ConvertError>`。
- `ConvertOptions` 字段、默认值和现有选项范围。
- `ConvertStats` 字段及计数语义。
- `ConvertError` 的 `kind`、`upstream_code`、`os_error`、`detail`。
- worker Request、Response、`PROTOCOL = 1` 和现有退出码。

内部错误使用 Rust 枚举与错误来源，不使用 C 状态结构。公开错误适配保留已有可对应的错误分类和兼容代码，包括现有测试要求的 `NoDanmaku / upstream_code = 8`。新增事务阶段错误使用既有分类，无法对应的 `upstream_code` 为 `0`，阶段信息放入 `detail`。

`ErrorKind::Locale` 保留反序列化兼容性，Rust 转换不再产生该错误。`version()` 标识 Rust 转换器及 DanmakuFactory 参考基线，不再声称运行 PCRE2。

#### 2.1.1 `version()` 调用方兼容性检查（Gate 0 必须完成）

Gate 0 必须搜索并记录 `version()` 返回值的所有仓库内生产调用方、示例、测试、发布及文档引用，区分展示、协议字段、子串判断和完整字符串判断。不得仅因其返回类型仍为 `&'static str` 就宣称兼容。

当前已核对到：

- `biliup-cli/src/danmaku_worker.rs` 将返回值写入 Converted 响应的 `version: String`。
- `danmaku-factory/examples/convert.rs` 在成功报告中显示返回值。
- `biliup-cli/tests/danmaku_worker.rs` 明确要求响应版本包含 `3813e93b`。
- 当前父进程读取 Converted 响应时按协议及结果字段处理，不能据此假设其他调用方也从不检查版本内容；Gate 0 必须复查全部匹配结果。

在已有检查没有发现其他约束时，返回值采用 `biliup Rust converter; DanmakuFactory baseline 3813e93b13b087e95901d1822baf9c3540e3f3f6`，保留参考提交标识而不宣称使用旧 C 或 PCRE2。Gate 0 记录版本格式和已有断言，增加版本字段序列化及调用方兼容性验收；不得通过删除 `3813e93b` 子串断言来掩盖兼容问题。若发现此前未知的完整字符串契约，先在本 Plan 中说明并审核适配方式，再进入 Gate 1，保持 worker JSON 字段和协议版本不变。

依据：[转换器版本接口](src/lib.rs)、[worker 响应](../biliup-cli/src/danmaku_worker.rs)、[真实 worker 测试](../biliup-cli/tests/danmaku_worker.rs)。

### 2.2 数据流与模块职责

采用以下流水线，内部类型不自动成为公共 API：

| 阶段 | 主要职责 |
|---|---|
| 原始 XML 弹幕 | 保存输入顺序、原始类型编号、属性和正文来源 |
| 标准化弹幕 | 类型映射、合法 UTF-8 文本、时间、颜色、字号及已解析的高级弹幕数据 |
| 过滤及排序结果 | 类型过滤、字号规则、完整稳定排序；保留输入序号 |
| `LayoutedDanmaku` | 确定时序、位置、运动、占用区域、样式及显示或屏蔽结果 |
| ASS Writer | 按确定顺序忠实序列化布局结果 |
| 输出事务 | 临时文件、完整写出、无覆盖发布、错误及残留清理 |

屏蔽状态与弹幕类型分开表达。重复过滤和密度过滤依赖正在显示的弹幕，应由布局调度阶段执行，不强行提前到纯文本过滤阶段。

`LayoutedDanmaku` 至少表达：

- 输入序号、开始与结束时间；
- 布局类型；
- 固定位置，或运动起止坐标、运动时间；
- 被占用的垂直区间；
- 样式引用、必要的字号和特效覆盖；
- 正文或高级弹幕载荷；
- `Dialogue`、保留为 `Comment`、省略的结果及原因。

布局阶段独占轨道与运动决策。Writer 不重新计算轨道、持续时间、屏蔽状态或碰撞结果。

#### 2.2.1 稳定排序的时间字段、精度与量化规则

标准化弹幕保留不可变的 `source_time_ms: i64` 和单调递增的输入序号。`source_time_ms` 是完成现有输入解析、偏移及毫秒舍入后、尚未进行 ASS 百分之一秒量化的时间。稳定排序只比较这一毫秒字段；相同键保持输入顺序，不额外按类型、正文或布局优先级重排。

时间处理顺序固定如下：

1. 业务入口保留当前 `f64` 秒转毫秒的舍入方式、`i64` 偏移/原点处理和三位小数的规范化 XML 输出。原始 XML 直接转换入口按 Gate 0 冻结的解析行为处理，不扩大为新的时间语义。
2. Gate 0 核对 C 的 `atof → f32 time → GET_MS_FLT` 路径、`EPS` 归零及浮点运算精度。实际 C 没有 XML 时间溢出拒绝规则，越界浮点转整数属于未定义行为；Rust 明确拒绝非有限值和超出有效 `i32` 毫秒/布局运算范围的输入。未单独批准时间精度修复前，Rust 的毫秒解析结果保持有定义的兼容契约；使用 `i64` 保存和检查算术，不借此静默放宽现有有效时间范围。直接转换已接受 500 小时，不套用业务入口 250 小时偏移过滤。
3. 在 `source_time_ms` 上完整稳定排序。不能先将秒转成整数秒，也不能先按 ASS 的 10 毫秒精度取整再排序；不使用浮点秒作为排序键。
4. 布局阶段另行生成 `ass_start_ms`：对有效的非负毫秒时间，沿用 `GET_ASS_MS_INT` 的 `((ms + 5) / 10) * 10` 规则，使用检查过的宽整数算术。保留原 `source_time_ms`，量化后不再次排序。
5. 配置持续时间及碰撞关键时刻沿用现有 `GET_ASS_MS_FLT` 的浮点精度和 `trunc(seconds * 100.0f + 0.55f) * 10` 量化契约，在布局中计算。Writer 仅序列化已经确定的时间，不重复舍入。

Gate 0 记录这些规则与 C 基线的对应关系；Gate 1/2 增加半毫秒附近、5 毫秒边界、较大时间偏移及浮点精度边界的最小用例。必须包含输入 `A@1004ms, B@1001ms, C@1001ms`：排序结果为 `B, C, A`，即使三个 ASS 开始时间都量化为 `1000ms` 也不得恢复输入顺序。毫秒解析本身产生的相同键按冻结契约处理，不把本次排序修复扩展为未经批准的浮点时间精度重写。

依据：[业务时间解析及规范化](../biliup-cli/src/server/workbench/renders/danmaku.rs)、[C 时间宏](../danmaku-factory-sys/vendor/DanmakuFactory/src/Define/DanmakuDef.h)、[C XML 时间解析](../danmaku-factory-sys/vendor/DanmakuFactory/src/XmlFile.c)、[C 布局量化](../danmaku-factory-sys/vendor/DanmakuFactory/src/AssFile/AssFile.c)。

### 2.3 必须保留的布局语义

Gate 0 冻结行为契约，Gate 2 据此实现：

1. **类型映射。** 明确 XML `1→右向左`、`6→左向右`、`5→顶部`、`4→底部`、`7→高级弹幕`。对其他编号、已有负值输入及统计行为按当前源码和样例记录，不顺手改成另一套类型解释。
2. **宽度与高度。** 当前 C 使用估算公式，不查询系统字体：高度为配置字号加文件字号相对 25 的差值；有效 UTF-8 的宽度按码点数乘高度再除以 1.2。新实现保留这一度量假设及取整规则，使用检查过的算术。不得未经批准引入真实字体测量、grapheme 或终端字符宽度算法。
3. **滚动碰撞。** 保留各方向的像素行占用及两个关键时刻：前一条完全进入屏幕的时刻、完全离开屏幕的时刻；同时检查新弹幕进入和到达另一边时是否追尾。不得用单一“轨道最后结束时间”代替。
4. **固定弹幕。** 保留顶部、底部扫描方向及共用的固定占用区域；保留边界比较的严格或非严格关系。
5. **密度。** 保留 `-1` 避免重叠、`0` 不设数量上限、正值限制同屏数量的语义，以及无可用位置时的现有回退规则。
6. **重复及高级弹幕。** 记录重复判断的有效时间窗口、比较文本阶段，以及高级弹幕对密度统计的贡献。
7. **显示参数。** 保留显示区域、滚动区域、行距、上下边距、字号归一化、颜色、透明度、描边、阴影和时间量化规则。
8. **输出。** 保留样式、ASS 标签、屏蔽事件及输出顺序语义。排序修复导致的顺序和后续布局变化必须归入对应 Intentional Change。

当前 C 确实使用方向独立的滚动占用数组和共享固定占用数组，碰撞规则见[排版实现](../danmaku-factory-sys/vendor/DanmakuFactory/src/AssFile/AssFile.c)。现有宽度公式见[字体度量实现](../danmaku-factory-sys/vendor/DanmakuFactory/src/String/DanmakuFactoryString.c)。

**类型 7 已在当前 Golden 和业务可接受输入中出现，属于本次范围。** 保留当前路径支持的定位、运动、透明度、旋转及字号等能力；用户名、礼物消息框、统计、正则黑名单、ASS 反向读取等扩展能力不纳入。

## 3. 兼容测试与有意变更的严格分界

### 3.1 Legacy-Compatible Tests

现有输入、配置和 Expected 作为不可变 Legacy 基线保留。新增 Rust Expected 与 Legacy Expected 分开记录，仅为批准改变的样例增加新期望。

要求：

- 未受批准变更影响的样例逐字节比较。
- 不运行批量覆盖 Expected 的生成流程来消除失败。
- Windows 参考输出沿用当前已有的 BOM、CRLF 归一化规则；除此之外不得用删除空白、重排事件或容差替换字节比较。
- 每个差异报告包含样例 ID、输入及配置摘要、参考版本、首个不同字节及行号、相关事件或输入序号，并标记解析、过滤、排序、布局、转义或序列化阶段。
- 对混合了兼容行为与批准变更的样例，保留原 Expected，记录受影响事件及原因，并增加独立审查过的 Rust Expected。
- 排序或正文改变可能影响后续占用和屏蔽结果；这些连带差异需要解释，不能整份输出直接豁免。
- 新发现的差异不得自行加入批准清单。无法证明属于既定变更时，阻塞相关 Gate。

现有 Golden 已具备输入不变检查和首差异定位能力，可在此基础上扩展，见[Golden 测试](tests/golden.rs)。

### 3.2 Intentional-Change Tests

每项变更必须记录“旧行为、新契约、原因、最小输入、独立断言、影响的 Golden、审核记录”。

| ID | 旧行为与新契约 | 最小验证及验收 |
|---|---|---|
| IC-01 时间排序 | 旧实现漏查第一对时间；新实现完整按时间升序稳定排序 | 输入时间 `[2,1,3]` 输出对应 `[1,2,3]`；覆盖两条、逆序和局部乱序；使用 2.2.1 的排序前毫秒字段 |
| IC-02 相同时间顺序 | 旧排序可能反转同时间元素；新实现保持输入顺序 | 带不同正文的同时间元素，在混合乱序输入中仍保持相对顺序；另测不同毫秒时间量化至同一 ASS 时刻仍不重排 |
| IC-03 完整长文本 | 移除输入及 ASS 转义阶段的 1023 字节截断 | 超过边界的 ASCII、中文、Emoji、组合字符全部保留；布局使用完整逻辑文本宽度 |
| IC-04 UTF-8 | 不再生成半个字符或依赖消费端丢弃坏字节 | 合法 Unicode 完整往返；非法 UTF-8、非法字符引用按明确错误返回；用原始输出字节验证 |
| IC-05 XML 与 ASS | XML 实体恰好解码一次；ASS 转义独立执行 | XML `&amp;lt;` 的逻辑正文为 `&lt;`，不再变成 `<`；覆盖实体、CDATA、换行、空格、花括号及字面量 `\N`、`\h` |
| IC-06 Locale | 移除 Numeric Locale 拒绝；解析和格式化始终使用 `.` | 独立子进程在 C locale 和已安装逗号小数点 locale 下，Rust 输出一致且成功 |

补充边界：

- `&amp;#55357;` 是合法 XML 中的字面文本，解码后不得再次作为数字字符引用处理。
- 直接出现的非法 Unicode 字符引用应返回可识别的输入错误。
- 使用 `quick-xml` 后对畸形 XML 的拒绝行为，需要与业务层现有严格校验对齐并记录；不得把解析器差异当成任意扩大拒绝范围的理由。
- 合法空文档与读到零条弹幕的既有公开错误契约保留。
- 尚未证明属于缺陷的宽度估算、时间舍入、模式映射、样式和边界比较先保持兼容。
- 每项 IC 必须经过独立于实现自测的差异审核；不得让新实现生成的输出成为其唯一正确性依据。

## 4. 输出事务、成功确认与崩溃清理

### 4.1 写入及发布流程

采用目标目录内的 `NamedTempFile`，复用现有依赖系列。该依赖从转换 crate 的开发依赖提升为生产依赖，不新增平台 FFI。

流程固定如下：

1. 校验配置并完成解析、过滤、排序和布局；预先计算统计结果。
2. 在目标文件的父目录创建唯一临时文件，使用明确的转换临时文件前缀；此步骤不创建、截断或替换最终目标路径。
3. 使用该临时文件原有句柄，通过 `BufWriter` 序列化 ASS，所有输出调用检查 `write_all` 等返回值。
4. 显式调用并检查 `flush()`，再通过 `into_inner()` 检查并取回同一有效句柄。
5. 发布前调用并检查 `sync_all()`，以覆盖可观测的延迟写入错误。此处同步文件，不承诺父目录项的断电持久性。
6. 完整写出后调用 `persist_noclobber` 发布，禁止后续再写目标文件。
7. 发布成功即为转换库的提交点；其后仅释放资源并返回已经计算好的成功结果，不增加可能改变转换结果的操作。
8. 发布前失败时显式清理临时文件，并检查删除结果。保留主错误，清理失败作为附加阶段信息记录。

步骤 2 的正确性不依赖预先检查目标不存在：若目标已存在，可提前返回 `OutputExists`，但该检查仅改善错误反馈；创建后至发布前目标仍可能出现，必须由步骤 6 作最终无覆盖裁决。

不得使用普通 `rename`、`persist` 或“检查不存在后复制”替代无覆盖发布；不得在发布失败后降级为覆盖写入。

### 4.2 能力边界

| 性质 | 本方案保证与限制 |
|---|---|
| 不覆盖已有目标 | 使用 `persist_noclobber`；文件、目录和符号链接等已有路径均不得被本次转换替换或删除 |
| 最终路径不暴露部分内容 | 所有写入和检查在临时文件完成；发布后不修改内容 |
| 并发同目标 | 不同转换各有临时文件，仅一个发布成功；失败方只清理自身资源 |
| 崩溃清理 | RAII 覆盖正常返回及展开；强制终止由工作目录所有者回收 |
| 断电持久性 | 不承诺；没有父目录同步和文件系统专项验证，不能声称崩溃后一定位于最终路径 |
| 跨平台严格原子性 | 不作统一承诺；临时名消失和最终名出现不一定构成一个不可分割操作 |
| OS close 错误 | 用户已确认采用安全 Rust 边界；不为获取 close 返回值引入 unsafe 或平台 FFI |

已核查的 `tempfile 3.27.0` 实现会在部分 Unix 系统优先使用无覆盖 rename，必要时回退为硬链接加删除临时名；后者可能留下两个名字。因此可以验收“不覆盖”和“发布完整内容”，不能宣称所有平台上的整个流程严格原子。

`NamedTempFile::close()` 返回的主要是删除错误；不能把它记为完整观测了 OS close 返回值。标准库 `File` 的析构忽略关闭错误，本方案通过显式写入、flush、取回句柄和同步建立可验证边界。

依据为已核查的官方 API：

- `https://docs.rs/tempfile/3.27.0/tempfile/struct.NamedTempFile.html`
- `https://doc.rust-lang.org/std/io/struct.BufWriter.html`
- `https://doc.rust-lang.org/std/fs/struct.File.html`

### 4.3 错误映射

| 阶段 | 公开分类 |
|---|---|
| 临时文件创建失败 | `OutputCreate` |
| 写入、flush、取回缓冲句柄、sync 失败 | `OutputWrite` |
| 无覆盖发布发现目标已存在 | `OutputExists` |
| 其他发布失败 | `OutputCreate`，`detail` 标明 `publish` 阶段 |
| 解析、配置和布局失败 | 保持现有相应分类 |
| 失败后的清理错误 | 不覆盖主错误；附加临时文件及 cleanup 阶段信息 |

保留平台错误来源。Unix 保留原始 OS 错误；Windows 不把 Win32 错误冒充历史 CRT errno，兼容现有字段约定并在 `detail` 中保留原始说明。

### 4.4 worker 与父进程确认

ASS 发布和 worker 结果 JSON 发布不是一个文件系统事务。必须区分：

- ASS 完整发布；
- worker 成功写出响应并正常退出；
- 父进程接受转换成功。

父进程仅在以下条件同时成立时接受成功：正常成功退出、响应协议有效且为 Converted、预期 ASS 存在且可读取、接受成功的检查点尚未取消。

若 worker 在 ASS 发布后、响应前被终止，可能留下完整但未确认的 ASS。它仍属于私有工作目录，不得被解释为成功产物；父进程在回收 worker 后清理。

当前 `run_worker` 启动前会直接删除输出路径，见[现有 worker 调用](../biliup-cli/src/server/workbench/renders/danmaku.rs)。重构时必须移除此无条件删除行为：

- 每次尝试拥有独占工作目录，响应文件不跨尝试共享。
- 已有目标交给无覆盖发布返回错误。
- 只有确认归属于已结束失败尝试的私有目录才能作为整体回收。
- 通用转换 API 不扫描用户目录、不按前缀批量删除文件。

### 4.5 取消、超时及残留策略

- 显式取消或超时：终止 worker，等待进程退出，再清理自身临时文件和未确认的私有输出。
- 请求 future 被丢弃：由存活的转换监督任务持有进程及工作目录所有权；丢弃请求触发取消，监督任务完成 kill、wait、cleanup。不能只依赖 `kill_on_drop` 就声称删除已完成。
- 父进程或系统崩溃：复用任务恢复及私有工作目录清理机制；只清理不再活动的受管目录，不对任意目标目录执行全局清扫。
- 独立调用转换库的进程被强制终止：允许留下有明确前缀的临时文件，由调用方管理；最终路径不能包含半写入内容。
- 删除因 Windows 共享句柄、权限或其他文件系统错误失败：记录残留，保留失败状态，下次受管恢复重试。不得报告已清理。

当前任务恢复已清理任务私有 `work` 目录，见[恢复和清理实现](../biliup-cli/src/server/workbench/renders/jobs.rs)。Gate 4 必须验证所有权与进程生命周期，不能仅凭现有清理代码宣称覆盖崩溃恢复。

## 5. 资源预算、平台行为与测试矩阵

### 5.1 资源约束

当前业务层已有 128 MiB XML、100 万条弹幕、120 秒转换和 15 秒自检限制，另有 250 小时时间偏移过滤；独立 worker 请求直接调用转换器，没有相同的资源校验。相关常量及调用路径见[业务入口](../biliup-cli/src/server/workbench/renders/danmaku.rs)。

新实现按以下规则传递约束，不新增任意的单条文本长度限制：

| 资源 | 设计及验证 |
|---|---|
| 原始 XML | 保留 128 MiB 业务上限；读取过程中计数，不能只依赖读取前的 metadata |
| 弹幕数量 | 在构建列表过程中执行现有 100 万条上限，独立 worker 同样执行 |
| 单条及累计正文 | 取消 1023 字节截断；受来源文件预算和累计解码正文预算约束，不无限制增长 |
| 归一化 XML | 允许实体重编码产生的合理膨胀，采用由现有预算和序列化格式推导的上界 |
| XML 解析 | 使用事件读取和可复用缓冲，不构建 XML DOM；不加载外部实体或 DTD |
| 高级弹幕载荷 | Gate 0 证实为历史分隔字段格式，并非 JSON parser；使用安全、有界的字段读取及明确类型，保留 `/n`、缺字段和原始 ASS 标签语义，不引入 JSON escape 的额外行为变化。worker JSON 继续保留 Serde JSON 默认递归限制 |
| 内存 | 正文所有权沿流水线移动，避免多份完整正文及每条重复保存公共样式；不累计整份 ASS |
| 超时与取消 | 保留现有 120 秒转换和 15 秒自检；有进程回收及残留清理验收 |
| 文件系统 | 临时创建、写出、同步、发布和删除分别检查及报告 |

归一化预算不得直接再次套用原始 128 MiB，否则可能拒绝此前合法但重编码膨胀的输入。原稿候选公式为 `B = 5 × S + N × H + P`；**其中的固定系数 5 必须先通过 Gate 0 的完整链路证明和验证，不能直接写成实施常量。** 证明前统一使用待验证的符号形式：

`B = E × S + N × H + P`

其中：

- `S` 为现有原始 XML 字节预算；
- `N` 为现有弹幕数量预算；
- `E` 为从预算所约束的来源文本到规范化 XML 正文的已证明最大字节膨胀系数；
- `H` 为现有规范化格式中单条标签及属性的最大非正文开销；
- `P` 为文档头尾开销。

Gate 0 根据现有字段范围及序列化格式算出并记录 `E/H/P`，添加预算推导测试；这些值不得凭经验拍定。只有证明当前完整链路满足 `E = 5` 后，才能采用原稿的 `B = 5 × S + N × H + P`。原始读取、归一化写入及 worker 读取都执行相应计数，正文解码后的累计字节也受来源预算约束。该预算通过内部公共常量或共享预算代码保持一致，不新增 JSON 协议字段。

不承诺“所有分配失败都能返回 OutOfMemory”：可恢复的预分配错误返回错误，进程级 OOM/abort 由父进程识别为 worker 失败。当前没有严格 OS RSS 上限，输入预算不能被表述为硬内存隔离。

入口分层：公开 raw API 按读取过程限制 128 MiB；内部 worker 入口允许已归一化 XML 的推导上界，并同时限制一百万节点和累计一次解码后完整 `d` 载荷 128 MiB（含高级参数及尾随字段）。Request 不增字段；独立 worker 请求也执行这三项预算。现有协议无法证明输入来源，不宣称所有手工 worker 请求的原文件上限仍为 128 MiB。

#### 5.1.1 Gate 0 的膨胀关系证明与验证

Gate 0 必须以当前生产函数和全部归一化步骤为依据，交付可审查的证明及可重复测试，不能只引用 XML 常识或另写一份理想化转义函数。

当前 `escape` 依次执行 `& → &amp;`、`< → &lt;`、`> → &gt;`，见[实际转义及规范化路径](../biliup-cli/src/server/workbench/renders/danmaku.rs)。对单次函数调用，候选字节界限来自以下关系：

- ASCII `&` 从 1 字节变为 5 字节，`<` 和 `>` 从 1 字节变为 4 字节；其他 UTF-8 字节不变。
- 当前替换次序不会再次处理后续替换产生的 `&`，也不会递归处理同一次替换的产物；必须检查实际调用次数，不能把一次调用的界限直接套在多次调用的链路上。
- 输入是字节预算，证明必须比较 UTF-8 字节长度，不能用字符数替代。连续 `&` 是候选系数 5 的达到上界样例，而非完整链路已经验收的证据。

完整证明还必须包含：

1. 从原始 XML 到逻辑正文的实体解码、CDATA、换行处理及其他变换，证明累计逻辑正文的字节数确实受 `S` 控制；不得假设已禁止的 DTD/外部实体仍能展开，也不得忽略其他可能复制正文的步骤。
2. 从逻辑正文到规范化 XML 的全部编码及序列化步骤，确认没有额外转义、重复包装、JSON 重编码或隐藏拷贝改变输出长度关系。若存在额外变换，重新推导 `E` 或更精确的组合上界，不以放宽固定系数绕过证明。
3. 根据实际可接受的时间、类型、字号、颜色及固定字段推导 `H`；计入分隔符、换行、精度、符号和可能出现的最大数值长度。`P` 取实际文档头尾字节数。
4. 对预算运算使用检查过的整数运算；验证边界的包含关系、超限检测、读取期间文件增长和归一化写入计数。溢出不能使预算回绕为较小值或失去限制。

测试至少包含空文本、纯 `&`、纯 `<`/`>`、混合文本、中文、Emoji、组合字符、已有实体字面量、数字实体及 CDATA，经实际业务路径归一化后检查输出长度不超过推导上界。另使用可复现的生成输入验证组合关系，并测试 `S/N/H/P` 边界及超限拒绝；大预算边界可由可配置的内部测试预算缩小复现，不能修改生产约束来迁就测试。

**验收：** 证明、实际函数测试和预算边界测试一致，`E/H/P` 有源码及字段范围依据；证据缺失或上界被反例打破时 Gate 0 不通过，禁止在 Gate 1 中先固化候选系数。

### 5.2 布局和性质测试

必须验证可观察结果：

- 长短文本混排，确认宽度、速度及追尾检测；
- 中文、Emoji、ZWJ 和组合字符，验证明确的现有度量假设；
- 多条同时间弹幕及稳定输入顺序；
- 高密度、`-1/0/正值` 三类密度配置；
- 前一条刚好进入、刚好离开，以及前后一个量化单位的碰撞边界；
- 顶部和底部共用占用区域；
- 不同字号、行距、边距、分辨率及极小显示区域；
- 类型过滤、重复屏蔽、保留 Comment 与省略模式；
- 高级弹幕的位置、运动及密度贡献；
- 相同输入、配置重复运行的确定性。

Property 测试使用可复现种子及失败输入保存，优先使用现有依赖，无需为测试名称专门引入新框架。至少检查稳定排序、统计约束、输出 UTF-8、布局区间合法、序列化忠实及受控输入不触发未处理 panic。

不得声称现有引擎保证所有方向或所有模式永不重叠；性质断言必须对应冻结的具体规则。

### 5.3 文件事务与进程测试

至少覆盖：

- 目标已存在、目录、符号链接和输入输出同路径；
- 多线程和多个真实 worker 发布同一路径，只有一个成功且结果完整；
- 创建、写入、flush、sync、发布和删除失败；
- 现有真实文件大小限制测试，以及可重复的阶段故障注入；
- 写入中、发布前、发布后响应前强制终止；
- 响应发布失败、协议错误、异常退出及请求 future 被丢弃；
- 清理失败及恢复重试；
- 失败方不删除其他转换的成功目标。

故障注入只验证对应失败阶段，不能替代真实文件系统及进程集成测试。

### 5.4 跨平台验收

Linux、Windows、macOS CI 必须覆盖：

- Unicode、空格、相对及绝对路径，Windows 长路径；
- 已有目标和无覆盖竞争；
- 句柄释放后可重命名、删除；
- 发布、取消、强制终止和残留回收；
- Locale 独立性；
- 平台支持范围内的本地文件系统行为。

保留既有平台文件封装：Windows BOM/CRLF 与其他平台 LF 的差异继续显式记录。跨平台确定性比较采用现有受限归一化，不宣称原始文件字节完全相同。

核心解析、布局和 Writer 测试不依赖系统字体。真实媒体路径沿用仓库现有字体资产和 FFmpeg 集成测试，不新增字体探测或业务功能。

无法执行的操作系统和文件系统场景标记为待 CI 验证。网络文件系统、异常挂载及断电恢复没有专项验证时，不扩展保证范围。

## 6. 实施阶段与 Gate

所有 Gate 共用以下规则：

- 验收依据包含命令退出码、行为断言、差异及必要产物，不能只记录“测试全绿”。
- 前置 Gate 未通过不得切换生产调用或删除参考能力。
- 失败时保存最小输入、配置和报告，修复原因；禁止弱化断言、批量刷新 Expected 或偷偷放宽预算。
- 新增行为或性能预算调整必须先更新本主 Plan 并审核。
- 不要求为每个 Gate 再创建独立状态文档；证据索引维护在主 Plan，机器可读清单与测试资产就近保存。

`#![forbid(unsafe_code)]` 约束本次新 Rust 核心和最终生产转换库。Gate 1–3 新增的 Rust 核心模块先执行这一约束；过渡期尚未切换的旧 FFI 包装层及冻结 C oracle 保持原状，不通过 `allow(unsafe_code)` 绕过新核心约束。Gate 4 切换公共 API 后，对生产转换库整体启用 `forbid(unsafe_code)`；C 差分参考通过独立参考程序运行。Gate 6 删除旧 C 及构建依赖后再次验证完整约束，不因保留参考能力要求把 C ABI 或 unsafe 放回生产库。

### Gate 0 — 基线冻结与测试准备

- **前置条件：** 核对实际 HEAD、工作区及本 Plan；有未提交用户修改时明确排除，不覆盖。
- **实施范围：** 冻结当前 C 源码、补丁、工具链、编译参数、配置、30 个 Golden、错误及 worker 行为；补齐布局契约、预算推导和测试分类。逐项完成 5.1.1 的实际膨胀关系证明、2.2.1 的排序时间及量化基线、2.1.1 的 `version()` 调用方兼容性检查。
- **交付产物：** 来源及哈希清单、可重建的 C oracle、Legacy 资产、IC 清单、差异报告格式、性能工作负载；另包含 `E/H/P` 的证明及测试、排序前毫秒/ASS 量化对照用例、版本调用方清单及冻结的版本字符串契约。
- **验证方法：** 在隔离构建目录从冻结提交构建 `convert` example；运行现有转换、worker 和 C sanitizer 测试；核对现有 CI 的原版/补丁版参考生成方法。预算测试必须调用实际归一化路径；时间测试检查毫秒舍入及量化先后；版本检查覆盖 worker 响应、示例输出及 `3813e93b` 断言。
- **验收标准：** 可从记录重建 oracle；冻结资产哈希一致；所有样例有归类，C 依赖和差分路径可重复运行；膨胀上界已证明且测试无反例，排序键与量化顺序已冻结，`version()` 调用方兼容性已确认。任一项未完成均不得通过 Gate 0。
- **禁止提前执行：** 删除或改写 C/patches、修改 Legacy Expected、合入历史移植或切换生产后端；未经证明直接使用固定膨胀系数，或未核对调用方就更改版本格式。
- **失败处理：** 停在 Gate 0，区分环境缺失与真实失败；不得把不可重建的参考二进制当成充分基线。预算反例、时间精度差异或版本契约冲突必须先修订并审核对应设计，不能留到实施后通过改测试处理。

基线记录至少包含 DanmakuFactory `3813e93…`、PCRE2 `6f9d7c13…`、7 个补丁哈希、完整项目 SHA、锁文件哈希、`rustc -Vv`、Cargo、C 编译器、目标平台、优化参数、Locale 和测试配置。

现有 `generate.py` 会写输入、配置及 Expected，只允许在隔离基线副本中运行。

### Gate 1 — Rust 模型、解析及基础处理

- **前置条件：** Gate 0 通过。
- **实施范围：** 在现有 crate 增加内部 Rust 模型、XML/高级弹幕解析、类型过滤、字号规则及稳定排序；实施已批准的文本、实体、Locale 修复。
- **交付产物：** 标准化数据契约、解析及过滤实现、IC-01 至 IC-06 的独立测试、资源预算执行代码。
- **验证方法：** 转换 crate 单元测试、最小输入断言、固定种子 Property 测试及畸形输入测试；使用 Gate 0 证明的预算及 2.2.1 的排序时间规则。
- **验收标准：** 解析和排序结果可直接断言；所有正文完整、实体只解码一次；边界限制在构建过程中执行；未批准的模式映射不变；不同毫秒时间即使量化至同一 ASS 时刻也保持正确时间顺序。
- **禁止提前执行：** 切换 worker、删除 C 或将未完成布局接入公共接口。
- **失败处理：** 修复对应模块；遇到新的语义差异先归因，不扩大 IC 清单。

### Gate 2 — 布局引擎

- **前置条件：** Gate 1 通过，布局契约已冻结。
- **实施范围：** 滚动、逆向、固定及现有高级弹幕布局；像素区间占用、追尾检测、密度、重复屏蔽和边距缩放。
- **交付产物：** `LayoutedDanmaku`、布局状态及可定位的布局测试。
- **验证方法：** 将 C ASS 中的运动、位置、时序及样式与 Rust 中间结果比较；执行混排、临界时刻、高密度和极小区域测试；检查排序后的时间量化及碰撞关键时刻。
- **验收标准：** 未批准变化的布局决策一致；IC 连带变化有解释；重复运行确定；Writer 不参与布局，也不重复量化时间。
- **禁止提前执行：** 用简单轨道模型替换原碰撞规则，或加入真实字体测量、GPU、SIMD、Rayon、内存池。
- **失败处理：** 保留差异轨迹，修正公式、取整、占用更新或扫描方向；不通过改 Expected 消除差异。

### Gate 3 — ASS Writer 与输出事务

- **前置条件：** Gate 2 通过，关闭错误边界按本 Plan 执行。
- **实施范围：** 忠实序列化布局结果，完成临时写入、显式检查、无覆盖发布及清理。
- **交付产物：** Writer、文件事务、阶段错误映射、并发及文件系统测试。
- **验证方法：** 运行转换 crate 测试；逐阶段故障注入；真实已有文件、发布竞争、文件大小限制及进程终止测试。
- **验收标准：** 不覆盖；最终路径无部分内容；错误可识别；失败方不删成功方；清理失败有记录；文档保证与平台实际行为相符。
- **禁止提前执行：** 普通 rename 覆盖回退、发布后继续写入、把临时文件 close 等同于检查 OS close。
- **失败处理：** 阻塞输出集成；不以更弱的发布方式绕过平台失败。

### Gate 4 — worker 集成与兼容性验收

- **前置条件：** Gate 1–3 通过，C oracle 保持可运行。
- **实施范围：** 公共接口转接 Rust、worker 生命周期及成功确认、取消清理；完成 Legacy、Differential、Property、异常输入和真实入口测试。
- **交付产物：** API/JSON 兼容测试、全部差异报告、IC 独立审核、取消与崩溃恢复证据。
- **验证方法：** 运行转换 crate、真实 CLI worker、渲染弹幕模块测试；覆盖 Python worker 启动路径及现有媒体集成路径。
- **验收标准：** 未批准行为逐字节一致；每项 IC 单独验收；退出码、字段和错误适配兼容；`version()` 满足 Gate 0 冻结的调用方契约；取消或错误不被认作成功；进程被回收后才完成清理。
- **禁止提前执行：** 删除 C、停止差分测试、把源码已切换或编译成功当成验收完成。
- **失败处理：** 保持发行切换受阻，保留 oracle；只修复已授权模块，不新增自动回退 C 的产品行为。

现有验证入口：

```sh
cargo test --locked -p danmaku-factory-sys -p danmaku-factory
cargo test --locked -p biliup-cli --test danmaku_worker
cargo test --locked -p biliup-cli --lib server::workbench::renders::danmaku::tests
```

新增测试纳入对应 package 的正常测试入口，避免必须记住独立手工脚本才会执行。这些包含 `danmaku-factory-sys` 的命令用于 Gate 0–5 的过渡期；Gate 6 必须将默认入口更新为无 C 参考依赖的 Rust 测试，历史命令只保留在基线来源说明中。

### Gate 5 — 性能与跨平台验收

- **前置条件：** Gate 4 通过，行为及 Expected 已审核。
- **实施范围：** 相同机器、构建档位、输入和同步策略下比较 C/Rust；完成三平台 CI。
- **交付产物：** 耗时、CPU、峰值 RSS、输出大小、清理时间和环境记录；兼容工作负载与有意变更工作负载分开报告。
- **验证方法：** 使用冻结的小型、密集、同时间、长文本及接近既有预算的工作负载；预热后重复测量；分别测核心处理和含同步的端到端时间。
- **验收标准：** 正常支持的工作负载满足既有超时；未批准语义变化的工作负载以 C 为默认资源预算，超出基线测量波动范围的回归必须定位并解决；已批准正确性变化的新增成本单列，不伪装为等量比较。无持续句柄或内存泄漏，三平台必测场景通过。
- **禁止提前执行：** 用不同输入、截断后的 C 输出或不同同步条件宣称 Rust 更快；擅自放宽阈值，或引入未经证明的优化架构。
- **失败处理：** 先 profile、分析复杂度和复制；若确需接受回归，先修订并审核预算，Gate 5 保持未通过。

没有既有硬 RSS 上限的部分只报告测量及复杂度界限，不伪造“已满足操作系统内存隔离”。某平台未运行即为该部分未验收。

### Gate 6 — C 退出与最终清理

- **前置条件：** Gate 0–5 全部通过；IC 独立审核结束；无需 C 的 Rust 行为测试已经独立运行。
- **实施范围：** 删除 `danmaku-factory-sys`、vendored C、转换使用的 PCRE2、patches、旧包装及其构建和专用测试；更新依赖、CI、发布及文档。
- **交付产物：** 单一 Rust 生产转换器、无 C 参考依赖的默认测试、保留来源和生成方法的 Legacy 资产。
- **验证方法：** 根工作区测试、桌面端锁文件检查、三平台转换/worker 测试、发布工具组装及依赖/引用扫描。
- **验收标准：** 生产转换 crate 启用 `forbid(unsafe_code)`；默认构建和测试不依赖已删除的 oracle；发布脚本、许可证路径和文档无失效引用；来源信息及历史再现步骤仍可查证。
- **禁止提前执行：** 因其他依赖仍使用 `cc` 或原生库而全局删除它们；删除 Rust 派生实现仍需保留的 DanmakuFactory MIT 声明。
- **失败处理：** 阻止清理变更合入；仅撤回本阶段自身的删除和引用修改，保持 C 参考能力；重新验证，不恢复旧 C 产品后端作为静默兜底。

最终检查至少包括：

```sh
cargo test --locked --workspace
cargo metadata --locked --format-version 1 \
  --manifest-path tauri-app/src-tauri/Cargo.toml
```

执行工作区测试前，沿用当前 CI 所需的前端构建和媒体测试环境。Git 历史中的冻结 C 提交可用于人工重建参考，但删除后的核心测试不得因此要求网络拉取或重新编译 C。

Gate 6 同步更新 Cargo Workspace、根及桌面端锁文件、CI、发布脚本、许可证及第三方声明、文档，以及旧 patches 和测试引用。源码链接在本 Plan 中作为冻结基线证据保留；删除目标文件后应转为明确的冻结提交历史路径或来源记录，不能留下貌似指向现存文件的失效链接。

## 7. 决策、待验证事项与已接受风险

| 分类 | 内容 |
|---|---|
| 已确认事实 | 当前 HEAD 与审计基线一致；本次创建前无独立 Plan；30 个 Golden；现有资源限制主要在业务层；类型 7 在范围内；worker 启动前存在无条件删除输出行为 |
| 已确定设计 | 单一现有 crate、Rust 原生建模、稳定排序、完整 UTF-8、一次实体解码、Locale 独立、保留 worker、事务写出、无覆盖发布、C 最后退出 |
| 用户已确认 | 保持 `forbid(unsafe_code)`，不为观察 OS close 返回值引入 unsafe/FFI；明确安全 API 可观测边界 |
| 实施验证 | 具体布局及取整等价性、实际归一化膨胀关系及预算常量、毫秒解析/排序/ASS 量化顺序、版本调用方契约、各平台发布/删除行为、监督任务回收、差异分类、性能和内存 |
| 已接受限制 | 不承诺目录项断电持久性；不承诺所有平台整个发布流程严格原子；无法完整观测 OS close；强杀可能留下临时名；没有新增硬 RSS 隔离 |
| 后续 Gate 阻塞项 | 未解释差异、缺失的 IC 审核、资源预算未证明或未落实、时间/版本契约冲突、平台测试缺失、回收或发布失败、性能回归未解决 |
| 文档交付状态 | 本主 Plan 已落盘；本次不执行 Gate 0，Gate 0–6 均未据本次文档保存宣称通过 |

## 8. 修订摘要、文档一致性与进入条件

本修订保留全部既定技术方向，重点补齐：

- 用临时文件、显式检查和无覆盖发布替换最终路径直接写入。
- 区分文件完整性、成功确认、清理、关闭错误、断电持久性和跨平台原子性。
- 将 C 删除推迟到 Gate 6，并保留可重建 oracle 和冻结资产。
- 分离 Legacy-Compatible 与 Intentional-Change 测试，禁止批量刷新期望。
- 明确布局中间表示及完整碰撞、密度和度量契约。
- 将资源预算传递至归一化和独立 worker，覆盖膨胀及读取竞争。
- 为 Gate 0–6 定义前置条件、产物、验证、验收、禁止事项和失败处理。

本次落盘追加三项门禁：

- **5.1/5.1.1 与 Gate 0：** 固定膨胀系数只有在实际 XML 解码、转义及规范化链路的上界证明与测试通过后才能采用；`E/H/P` 均需依据。
- **2.2.1、IC-01/02 与 Gate 0–2：** 明确排序使用 ASS 量化前的毫秒字段，保留输入序号；布局再按冻结规则量化，不允许提前截断或量化后重新排序。
- **2.1.1、Gate 0 与 Gate 4：** 核对并冻结 `version()` 所有调用方的格式契约，保留现有参考提交标识及 worker 字段兼容性。

文档一致性检查结论：

- 最终目标仍为移除本次转换使用的 C，实现顺序保留验证参考，删除只在 Gate 6 执行。
- 字节兼容要求只适用于未批准改变的行为，Windows 受限归一化没有扩展为任意忽略差异。
- 所有主动修复有独立测试及差异审核要求；时间解析精度没有被暗中列为额外修复。
- 文件发布保证没有超出已核查 API 的语义；存在性预检查不承担无覆盖正确性，完整但未确认的 ASS 不代表 worker 成功。
- 没有新增业务能力、完整正则引擎或平台 FFI。
- `forbid(unsafe_code)` 的新核心、公共接口切换及最终库验收时机明确，不与冻结独立 C 参考相冲突。
- Gate 0–6 依赖顺序明确，过渡期含 C 的验证命令不会被要求在删除后继续作为默认测试执行。
- 所有 Gate 均有可执行的验证及阻断条件。

**当前具备开始 Gate 0 的条件，Gate 0 尚未完成。** 方案修订轮仅做源码、依赖、官方 API 和 Git/metadata 核对；本次只保存完整 Plan、核对三项补充依据及检查文档。此前已通过的转换及 worker 测试属于历史基线证据，Gate 0 冻结时仍需按记录重新执行。

**本次唯一创建或修改的文件：`crates/danmaku-factory/PLAN.md`。** 未实施转换器、修改 Cargo 依赖或 Golden Expected、删除 C，也未 commit、push 或 merge。完成文档落盘与检查后停止，不自动进入 Gate 0。

## 9. 实施证据索引（2026-10-16 起）

本节覆盖上述历史“仅保存文档”的执行状态。用户原有唯一修改是未跟踪的本 Plan；冻结 HEAD 为 `76d03061053733d0c298677bf8ec22dac82263b8`，未 commit/push/merge。

### Gate 0：通过（Linux，2026-10-16）

- 来源、完整工具链/Locale/C flags、140 个源码/补丁/锁文件/Golden SHA256：`tests/baseline/source.json`。`python3 tests/baseline/oracle.py check` 验证冻结 Git 对象；`prepare` 在根 `target/danmaku-oracle` 重建独立 release `convert`，不依赖当前 Rust 核心。`golden` 实跑 30 个样例逐字节一致，结果在 `target/danmaku-oracle/golden-result.json`。
- 原版/补丁版 CLI 已从本地上游 Git 的固定提交在隔离目录编译；第一次 `git apply` 因嵌套目录无 `.git` 跳过，隔离再生成正确发现 `dense-edge` 崩溃。为隔离目录初始化 `.git` 后重做补丁，30 样例再生成全部与原输入、配置、Expected 一致；与无补丁版的差异恰为已有四项标记：`dense-edge`、`tiny-line-fills-area`、`tiny-one-pixel`、`trailing_ref`。未改原 Expected。
- 实跑 `cargo test --locked -p danmaku-factory-sys -p danmaku-factory`：原有 17 测试通过；随后新增预算测试另计。初次 Locale 子场景跳过；用 `localedef --no-archive -i de_DE -f UTF-8 target/danmaku-oracle/locale/de_DE.UTF-8` 生成隔离 Locale，`LOCPATH="$PWD/target/danmaku-oracle/locale"` 重跑通过且无跳过。
- `CC=clang crates/danmaku-factory-sys/tests/c/check.sh`：ASan/UBSan/LSan 和符号检查通过。`cargo test --locked -p biliup-cli --test danmaku_worker`：3 通过；`cargo test --locked -p biliup-cli --lib server::workbench::renders::danmaku::tests`：原有 16 通过。
- 时间基线：`tests/baseline/time.c` 直接使用冻结 C 宏，输出 `time.json`。普通秒先 f64→f32；`t<EPS` 归零（包括负数）；毫秒 `trunc(f32(t*1000+0.5))`；ASS 开始 `((ms+5)/10)*10`；配置/碰撞秒 `trunc(f32(s*100+0.55))*10`。高级 existTime 使用 f64 秒→毫秒。无额外时间精度修复。
- 预算证明：生产 `parse_xml` 只向当前正文追加每段 Text/CData 一次；DTD 被拒绝，无外部实体；实体引用解码后的 UTF-8 字节数不大于引用的来源字节数，CDATA 去包装不增加正文。因此累计逻辑正文 `L<=S`。生产 `escape` 只调用一次，顺次替换 `&/< />`，产物不再次被同一替换处理；最大字节膨胀 `&→&amp;` 为 5，故 `E=5`。已验证 mode 1..9、size 1..1000、color 0..16777215；±900000000ms 过滤及最小 origin 得规范时间 0..1800000.000s。最长空正文标签 `<d p="1800000.000,9,1000,16777215,0,0,0,0"></d>\n` 是 **48 字节**，头尾是 **47 字节**。`B=5*S+48*N+47=719088687`。常量以实际字面格式长度定义，检查算术溢出。`src/limits.rs` 和生产归一化函数的测试覆盖上界可达、256 固定种子组合、S/N/输出边界和读取前检查后的文件增长；结果待本轮测试完成记录。
- 版本全仓匹配只发现两个生产调用：worker Converted `version: String`，example 展示；worker 测试检查 `3813e93b` 子串；父进程不按版本字符串分支；发布、文档无完整字符串比较。冻结新格式仍为 2.1.1 指定字符串，JSON protocol/字段不改。C 自身版本声明及 C 专用测试只用于 Oracle。
- 性能输入：`tests/baseline/workloads.py` 可复现 small/normal/dense/same_time/long_text_ic03/special/near_limit。已生成清单、SHA256、原始字节数；near_limit 为 131828947 字节、180000 条且单条 689 字节。IC-03 工作负载另列；尚无 Rust 性能结论。

Gate 0 源码复核的最小事实修订（不新增 IC，不降低兼容要求）：

- 类型 7 不是 JSON parser：按分隔符顺序取字段，未找到分隔符时返回空字段并耗尽输入；`[0.5`、`[`、空正文均已被 C sanitizer 明确接受，坐标/时间/旋转=0，fade=255，正文/字体为空。只把 `/n` 变 LF，`\n`/`\u` 不解码，转义引号仍按实际双引号截断。采用安全、有界字段 tokenizer 保持这些行为；不引入完整 JSON 的语义变化。
- type7 正文绕过普通 `assEscape`，原始 ASS 标签及反斜杠是现有能力；IC-05 的普通 ASS 转义不能破坏它。type7 `save_blocked=false` 时无条件省略，未屏蔽节点仍贡献密度。普通预先屏蔽节点仍可能输出 Comment；仅布局阶段屏蔽分支在该选项关闭时省略。
- C 的 special 字体数组为 128 字节，却以 1024 字节上限复制，存在未修补越界；Oracle 禁用此类无定义输入。Rust 不复制固定缓冲区，明确检查数值运算，不把内存破坏或浮点→整数溢出当作兼容输出。
- 独立只读源码审查确认上述 tokenizer 选择及预算分层可保持业务目标；尚不构成后续 Rust 实现/行为验收。

布局冻结要点（对应 `AssFile.c:1853–2497,3333–3356,3726–3784`，`String/DanmakuFactoryString.c:35–97`，`List/DanmakuFactoryList.c:426–458`）：

- XML 1/6/5/4/7 映射 R2L/L2R/TOP/BOTTOM/SPECIAL；其他 short 值保留，故原始 2/3 也是 L2R/TOP。负值屏蔽独立建模；原始 -5 缺特殊载荷，公开返回 UnsupportedInput。所有成功读取节点计入总数，未知负值计 blocked；未知类型的事件序号使用排序后全节点序号。
- 合法 UTF-8 码点数 n（包括 ZWJ/组合符/换行）度量 `h=config_font+file_font-25`，`w=trunc((n*h)/1.2_f64)`。字号归一化只跳过当前正 SPECIAL；已屏蔽 special 仍参与全局 norm 触发/赋值。
- hold/roll 行数为 f32 height*area 截断并至少 1；scrollarea 仅进一步缩小 roll。占用高度 clamp(h+spacing,1,rows)。边距只改坐标。
- 每方向独立 enter/leave 像素数组。`T=ass_start,R=量化scroll_ms,X=宽度`；`enter_dt=Q((R/1000_f32)*w/(X+w))`，`cross_dt=Q((R/1000_f32)*X/(X+w))`，每一步 f32。候选每行须 `T>=enter && T+cross_dt>=leave`；可见时写 enter=T+enter_dt、leave=T+R。
- 顶/底共用 fixEndTime，冲突严格 `T<end[row]`，写 T+量化fix_ms。顶部自上，底部自下，区间上闭下开；无空位时 -1 屏蔽，其他回退。
- findMin 正向仅查 `[0,rows-height)`，逆向查 `[height,rows)` 且返回下标直接作 bottom exclusive；相等时保持原扫描优先级。边界单位置直接返回；原回退的同值清零副作用必须保留，已屏蔽普通节点也可能触发它。
- 密度只屏蔽普通节点；累计先前正普通/特殊且 end>T，等于结束不活跃。special 密度用原 exist_ms，输出结束另量化。重复跨普通类型，比较 ASS 转义前正文。
- special 四坐标全 `<1+EPS` 才全按分辨率缩放（负坐标不排除）；先比较 f32 再决定 pos/move，之后截坐标整数。fade、字体、旋转、运动字段和标签顺序照 C。普通 blur 标签仅 R2L 输出。

### Gate 1：通过内部流水线验收（Linux，2026-10-16）

- 新核心在 `src/native/{model,number,parse,special,escape}.rs`，根 native 模块 `forbid(unsafe_code)`；公共转换仍调用冻结 C 后端。quick-xml 精确解析到工作区已有 0.37.5，根/桌面锁文件同步，不引入新 parser 版本。
- `LOCPATH="$PWD/target/danmaku-oracle/locale" BILIUP_REQUIRE_LOCALE_TEST=1 cargo test --locked -p danmaku-factory --lib native::`：**21 通过**，包含 C 时间探针比对、稳定排序 128×256 固定种子、1024 个畸形字节输入、完整 Unicode/实体/CDATA/ASS 转义、预算、数值范围、选项范围、8 项高级字段测试及实际设置 LC_NUMERIC 的两个独立子进程。日志 `target/danmaku-oracle/native-gate1-tests.txt`。
- IC-01/02 在不可变 source_time_ms 上排序，明确断言量化相同的 1001/1001/1004ms 顺序；IC-03/04 保存超 1023 字节正文且非法 UTF-8/非法引用返回错误；IC-05 一次解码和普通 ASS 转义独立，type7 保留原 ASS；IC-06 的解析/数字序列化子阶段实跑 Locale 通过。完整 ASS 和 IC 连带布局差异验收仍属 Gate 2–4，不用此阶段单测代替。
- 输入逐事件读取，在构建列表前检查百万条限制，完整解码载荷累计 128MiB，reader 实际读取计数；worker normalized budget 类型已经定义，尚未接入生产 worker。
- 新发现且已保留的直接入口细节：四字段 `p="1,1,25,16777215"` 的 C 颜色为 0，只有第四字段后仍有逗号时才采用给定颜色；normalization 总有后续四字段。类型 0 不被 COLOR 误计为 blocked。均有直接断言。

### Gate 2：通过 Legacy 布局及边界验收（Linux，2026-10-16）

- `src/native/layout.rs` 完整实现独立方向像素 enter/leave、追尾检测、共享固定占用、原 findMin 回退副作用、密度/重复、type7 时序/运动/透明度和明确 LayoutedDanmaku。source_time_ms 不修改，Writer 所需时间/运动/层/样式/省略均在布局决定。
- `native::differential::legacy_layout_decisions_match_frozen_c_events` 独立读取 C Golden ASS，不调用新 Writer，逐事件对比 26 个未受 IC 影响样例的输出数量、Dialogue/Comment、层、样式、起止毫秒、pos/move 及运动时段、字号和像素区间。其余四输入留待 Gate 3/4 逐事件 IC 差异审核。
- 11 项布局边界/性质测试覆盖 660/670ms 追尾边界、方向隔离、顶/底共享及恰好结束、回退突变、type7 未量化密度贡献、重复跨类型、saveblocked 特殊语义、极小区域/字号/边距/blur、条件算术及固定种子确定性。曾发现错误测试只乘单字符未实际溢出，修正为双字符以触发真实 C 整数乘法溢出；曾发现批量活跃索引提前求值后续 special 时间，已按 C 重复省略的短路边界修复并添加回归。
- 全 native 测试（含 Gate 1）33 通过；日志 `target/danmaku-oracle/gate2-tests.txt`。活跃堆/正文哈希索引只保存索引，不复制正文；性能仍待 Gate 5 实测。

### Gate 3：通过（Linux，2026-10-16）

- `src/native/writer.rs` 流式序列化布局 IR，逐调用检查 I/O；保留 Windows BOM/CRLF、样式、普通转义和 type7 原 ASS。没有重新决定布局或屏蔽。`transaction.rs` 同目录独立临时文件，原 File 句柄→BufWriter→显式 flush→into_inner→sync_all→persist_noclobber；成功后只释放句柄。失败显式 close 清理，附加残留错误而不替换主错误。
- 41 项 native 测试通过（日志 `target/danmaku-oracle/gate3-tests.txt`）：25 完整 Legacy 输出逐字节一致；26 布局比对仍通过；五个 IC 输入逐事件保留原 Expected 并断言。新发现 `emoji.xml` 中 2..6 号正文含字面数字实体，属于既定 IC-05（所有布局保持 C 一致），已归类而未修改 Expected。
- IC-01/02 的完整下游输出由冻结 C Oracle 对独立稳定排列的原 XML 生成，保存在 `tests/baseline/intentional/unsorted-stable.{ass,json}`；生成器 `sorted_oracle.py` 拒绝覆盖。该参考不依赖新 Rust 的排序、布局或 Writer。其余 IC 直接断言完整文本、UTF-8 及未改变事件/布局，不批量生成 Rust Expected。
- 事务覆盖六阶段故障注入（create/write/flush/取回buffer/sync/publish）、清理失败保留真实残留并报告路径、8线程同目标无覆盖竞争、文件/目录/悬空链接已存在、成功后可重命名；独立真实子进程 RLIMIT_FSIZE 触发 EFBIG 并无残留。三个真实强杀阶段（写入/发布前/发布后）验证最终路径无半内容，发布后的内容完整，临时名残留由目录所有者清理。真实多 worker 发布、worker响应/监督生命周期仍在 Gate 4 验收。
- 独立只读审查未发现生产事务/Writer 缺陷，指出两项验收缺口后已补齐：Locale 子进程现跑完整 layout→Writer→同步事务并字节比较，长文本六事件的层/时间/屏蔽/坐标使用独立常量断言。审查另以独立 C `%g` 对比 50173 个固定数值样本，0差异。主代理重跑 41/41 通过；`cargo clippy --locked -p danmaku-factory --all-targets -- -D warnings` 通过。进入 Gate 4。

### Gate 4：通过本机完整集成验收（Linux，2026-10-16）

Gate 4 实施证据（验收进行中）：

- 公共 `convert_xml_to_ass`、options/stats/errors 形状及 worker PROTOCOL=1 保持；生产 crate 全局 `forbid(unsafe_code)`，`cargo tree --locked -p biliup-cli --prefix none` 仅出现 Rust `danmaku-factory`，不再依赖 sys。sys 源码/补丁仍保留作冻结 Oracle，未提前删除。
- API 外部测试保留 30 个原 Golden；`tests/support/mod.rs` 仅按独立审核的事件/字节转换五项 IC 预期，不从 Rust 输出生成。原 30 Expected 文件哈希未改。转接后 core/sys 测试 58 通过（43 unit、9 errors、2 golden、1 process、3 sys）；后续宽整数/解析边界新增测试另记。
- 公共 Locale 验收已移到独立 integration test host（unsafe 仅用于宿主 setlocale/rlimit，不进入生产 crate），实际启动两个子进程分别设置 C/逗号 Locale，调用完整公共 API 后逐字节比较 ASS；所需 de_DE 由本地隔离 LOCPATH 提供。
- tempfile 3.27 的私有 PathError 丢失 create errno，真实 errors 测试发现 OutputCreate 的 os_error=None 回归；改为 Builder.make_in 内以 create_new、Unix0600 创建并捕获实际 errno，保持原句柄及无覆盖事务，原错误断言恢复通过。
- 新发现 IC-03 的数值域后果：不能把原本会先截断的超长正文当 C width UB 而拒绝。native width/product/denominator/水平坐标扩为 i64（预算内最大乘积 <5e12，精确转 f64），保持小域 f64截断/f32运动顺序、时间及special数值域。13 布局测试包含实际64MiB正文和恰好128MiB完整XML流式解析→布局→Writer，仅保有一次正文而不累计ASS；初始 i32 布局拒绝问题已修正。
- 外部独立 C/Rust release 差分 `tests/baseline/differential.py` 实跑256组（seed0x3813e93b）Legacy安全输入，字节及统计全部一致；报告 `target/danmaku-oracle/differential/report.json`。宽度扩宽后最终重测待集成。
- worker监督在 `danmaku_process.rs`，Arc持有根目录，独占attempt持有XML/request/result/ASS，源XML Vec所有权移动并在写完后释放。请求drop触发取消；kill+确认wait后清理。正常退出、有效Converted、可读ASS及最终未取消同时成立才接受；JSON响应自身也无覆盖发布。启动前无条件删除已移除。
- worker进程/lifecycle定向测试由实现方实跑27/27（包含发布后取消/外部强杀、future drop释放根所有者、超时/崩溃、协议/响应/退出/ASS错误、成功检查点取消、清理失败残留、同根并发、父进程强杀后的存活worker租约、恢复重命名后迟到worker拒绝）；主代理最终集成复跑待完成。真实二进制integration 5/5通过，包括8个进程竞争同输出和已有响应文件不覆盖。
- 恢复在 `jobs.rs` 使用独占lease确认无活跃监督/worker，核对原root/token后先改为受管tombstone，再释放句柄并删除；失败记录原/残留路径，下次启动重试。未知旧目录不再盲删。新render/preview/selfcheck根目录立即注册；preview/selfcheck移至应用cache受管目录。原始/替换/损坏marker和活跃/残留恢复的主代理测试通过；最终完整路径复验待完成。lease128KiB上界覆盖Windows32767UTF16路径*最多3UTF8字节及JSON包装/转义（反斜线最多2字节），也覆盖Unix4096*6最坏JSON转义。
- `npm run build` 通过，真实字体工具脚本在 `target/danmaku-render-tools` 组装并校验SHA通过。三平台 `danmaku-native` CI已配置实际core/worker/recovery/Clippy命令；**未声称已运行CI**。本机只有Linux Rust目标，无Windows/macOS执行结果；Gate5尚不能通过，Gate6禁止删除C。

Gate 0 退出复核：新增预算单测 3/3、实际生产归一化测试 2/2 通过；独立编译的 C 时间探针、140 文件哈希复核、隔离 CLI 再生成全部通过。30 样例逐项归类及首差异/阶段报告字段在 `tests/baseline/classification.json`，六项 IC 的旧/新契约、最小复现、独立断言与待实现审核状态在 `tests/baseline/intentional-changes.json`。全仓格式差异已在冻结 HEAD 的隔离副本复现，日志 `target/danmaku-oracle/format-baseline.txt`；最终全仓检查仍有17个无关文件既有差异，未覆盖用户源码，转换crate格式检查已通过。

Gate 4 集成边界验证（性能优化前快照）：

- `LOCPATH=... BILIUP_REQUIRE_LOCALE_TEST=1 BILIUP_RENDER_TOOLS_DIR=... BILIUP_REQUIRE_RENDER_TESTS=1 cargo test --locked --workspace` **exit0，1572通过/0失败/9既有忽略项**，包含真实媒体、worker、受管恢复及49项native单测；日志 `target/danmaku-oracle/workspace-tests.txt`，机器统计 `workspace-summary.json`。9忽略项是原有外网直播/手工HA/音频样本等入口，没有新增skip。
- 真实 Python extension 路径 `cargo test --locked -p stream-gears --test danmaku_worker` **1/1通过**，实际加载本构建cdylib，经 `Launcher::python` 启动同模块worker，确认先于server初始化、Unicode路径、protocol/版本/统计、C Legacy bytes及句柄释放。
- 最小解析事实修正：C及业务层忽略编码声明标签，实际UTF8字节始终严格解析，删除Rust额外标签白名单拒绝。Linux保留原CR；Windows-only原始字节CRLF折LF（预算计原字节、实体解码前），保留bareCR。独立边界测试通过，C五种声明标签同UTF8正文实跑字节一致；未声称Windows实际运行。

### Gate 5：实施中，性能回归修复/跨平台结果待验收

- 可复现工具 `tests/baseline/benchmark.{py,rs}`（driver实际名 `benchmark_native.rs`）及 `benchmark_c.c`，同一个release驱动同时调真实native生产模块和冻结C函数，使用相同NamedTempFile→sync_all→persist_noclobber。核心不含sync/析构，E2E包含同步发布；CPUuser/system/getrusage、峰值RSS、输出及清理单列。输入/驱动/源码/锁/静态库/二进制hash和机器环境保存，代码改动后拒绝旧driver。
- 初始 `benchmark.py prepare`、`smoke`、`run --warmups 2 --repeats 5` 实跑7工作负载，6类兼容输出hash/统计一致，IC03长文本按不等量工作单列；原始报告保留 `tests/baseline/performance/linux-initial.json`。near_limit C核心3478.67ms、Rust556.10ms，峰值C140890112B、Rust209281024B（1.485倍，超出波动）——因此**未通过性能门禁**，未调整标准。
- 实际分配profile定位：源record144B、finalIR296B，180k节点旧Vec和新Vec并存；parsed152540KiB，layout峰204300KiB。先将仅special使用的载荷Box化，record72B/IR224B，实测峰降至178464KiB，仍高于C，继续修复。拟以安全Rust enum表达单record的Normalized/已布局阶段并原地转换，保留source_time_ms/input_sequence、完整正文和明确布局结果；无unsafe/GPU/Rayon/内存池或布局简化。此优化完成后必须重新跑行为、RSS及完整验收，不用优化前测试冒充最终结果。
- Linux峰值统计额外读取 `/proc/self/status VmHWM`，同时保留getrusage原值，因为后者可继承launch前RSS地板；这不改变near_limit的已证实回归。profile日志在 `target/danmaku-oracle/profile-near*`/`profile-box-near*`。
- 远端 `refactor/rust_danmaku` 分支不存在（GitHub API404、git ls-remote空），无对应CI运行。任务明确禁止未授权commit/push，当前本地修改不能由远端CI取到；未触发会测试旧源码的无关workflow。三平台矩阵已配置但Windows/macOS无真实结果，Gate5未通过，Gate6维持禁止删除C。
- 经真实分配profile继续把普通记录压至64B，使用单Vec的安全Rust阶段enum、Box<str>和special独立载荷；原始source_time_ms和输入序号仍保留。已决定的水平半宽/屏宽以无损紧凑字段存储，Writer view只展开，不重新选轨/测宽；极端字号有独立完整宽字段分支。容器地址/容量、正文地址、排序键保持的性能回归测试及全native47项通过。64B单次profile峰141991936B，仍比同轮C140935168B高约1MiB，正在定位剩余分配差，未默许放宽标准。

Gate 4 后续生命周期审查修复（不以前快照代替最终验证）：

- 真实删除可在删掉root内部lease后因另一文件权限失败；新增root外兄弟manifest在独占lease下完整flush/sync/无覆盖发布，持有独占manifest锁直到删除完子树，恢复可在内部marker消失后安全重试。manifest临时文件先位于私有root，强杀残留也可回收。5项恢复测试通过，包括实际Unix权限失败、marker已消失、manifest发布后/rename前及root删除后中断。
- 用 `ManagedRoot` 代替相关 `Arc<TempDir>`，最后所有者显式检查/记录清理，不再依赖忽略删除错误的TempDir析构。normal preview/selfcheck/render接受点检查失败；错误/丢弃future路径记录并保留受管恢复身份。worker/目录定向30项通过。
- 迟到worker必须通过受监督启动信号验证attempt marker；恢复删marker后不能静默退为独立worker。新增保留request/XML、删marker后的真实进程拒绝断言。
- render先发布自有MP4 link后root清理失败的连带问题已处理：仅回滚本次create-new成功的link，检查删除错误并返回失败，保留其他任务产物，避免无响应成功文件阻塞后续重试。真实文件系统回归1/1通过。未修改通用FFmpeg进程辅助实现。

Gate 5 Linux 性能验收（最终64B/容量提示快照，三平台Gate整体仍未通过）：

- 用隔离变体核实C node56B对应glibc64B块、689/690B正文同一分配档位；差异来自Vec增长及元数据过度预留与Linux THP `[always]` 的交互。最终同句柄metadata只作best-effort提示，初始metadata请求不超过source字节数，容量/字节/百万数量受现有预算约束；预留失败回退按需增长，不把hint当额外拒绝条件。实际读取及构建预算不依赖metadata。
- `benchmark.py prepare` 后 `run --warmups 2 --repeats 5` 最终**8类、112次转换**全部成功；7类兼容工作负载输出hash、统计和重复确定性一致；IC03单列。完整原始报告（含CPU user/system、阶段耗时、RSS、输出大小、cleanup、来源hash及环境）为 `tests/baseline/performance/linux-final.json`。机器i5-13400/16逻辑CPU/62GiB RAM、Linux7.2.9、glibc2.44、btrfs、release LTO/codegen-units1，交错C/native，未变更系统缓存/频率/THP。
- 兼容核心耗时中位数 C→Rust：small0.142→0.117ms、normal27.89→13.93ms、dense66.99→31.76ms、same_time31.59→20.71ms、special19.92→15.23ms、near_limit3921.19→600.61ms、near_count458.16→291.89ms。near_limit峰值141168640→141156352B，normal4218880→4026368B，million-node近数量上限98963456→66891776B；其余兼容RSS与C波动范围重叠或更低。清理差别在相应C观察波动范围内，没有未定位的持续回归；所有支持输入满足120s预算。
- IC03 long_text工作量不等：C截断输出，Rust完整保存；峰值5144576→11259904B、输出大小和同步/删除成本按原始报告独立列示，不算兼容性能比率。完整128MiB合法文本的正确性已单独实跑；输入预算不冒充RSS硬限制。
- 初始/紧凑未预留/过度预留报告独立保留，不覆盖失败证据；最终RSS修正使用各阶段`/proc VmHWM`观测最大值，并另存getrusage值，避免launch前地板和阶段计数近似影响。性能以最终报告为准，之前单次probe不作为验收。
- 本机Windows/macOS目标/运行器不可用，Docker当前无运行中的其他平台容器，远端无本地分支；需要将当前具体源码交给三平台执行环境才能完成Gate5。禁止提前执行Gate6仍有效。

最终本机验收索引：

- 最终核心/worker/恢复代码重新执行 `LOCPATH=... BILIUP_REQUIRE_LOCALE_TEST=1 BILIUP_RENDER_TOOLS_DIR=... BILIUP_REQUIRE_RENDER_TESTS=1 cargo test --locked --workspace`，**exit0，1584通过/0失败/9既有忽略项**；21测试suite明细在 `target/danmaku-oracle/workspace-final-summary.json`，完整输出 `workspace-final-tests.txt`。原有C/sys仍参与过渡workspace测试，生产依赖树不含sys。
- 最终release转换 example构建通过；外部C/Rust256组差分重跑全部字节/统计一致，`target/danmaku-oracle/differential-final/report.json`。纯Rust core全部50项native测试通过（另外limits/api单测），含完整128MiB输入；IC-01..06分类文件逐项记录审核依据，未改Legacy Expected。
- 在全workspace边界后追加实际type7独立worker断言，`cargo test --locked -p biliup-cli --test danmaku_worker` **6/6通过**；对advanced move/fade/rotation/font/固定位置及blocked统计逐字节验证。清理失败测试随后直接调用真实恢复helper，确认最后owner保留失败身份后恢复完成，定向 **1/1通过**。
- `cargo clippy --locked -p danmaku-factory --all-targets -- -D warnings` **通过**；CLI受影响crate使用 `cargo clippy --locked -p biliup-cli --lib --no-deps` **通过（原有lint保留）**。初次带workspace依赖lint的CLI检查在无关生成Douyu签名代码上消耗约8分钟CPU后取消，exit255日志 `cli-clippy.txt`，不记为通过；未修改无关生成代码或放宽断言。
- `cargo fmt -p danmaku-factory -- --check`、所有本次改动Rust文件的rustfmt检查、`git diff --check`通过；`cargo fmt --all -- --check`仍因**17个本次未改动文件**的既有格式差异失败，与冻结HEAD相同，`final-format-check.txt`。没有把全仓格式失败记为成功。
- 根/桌面 `cargo metadata --locked`检查通过；`npm run build`通过；最终render-tools脚本组装、字体SHA、MIT文件与native notice复制一致性检查通过，test/release/desktop workflow YAML解析通过。原C/PCRE2来源/许可证仍保留Oracle crate；新增native MIT副本及第三方声明，发布脚本仅更新实际生产notice来源。
- 最终Git：18个跟踪文件修改，39个未跟踪文件（含用户原Plan，其他为新核心/测试/基线/性能/声明），无删除、无暂存、无commit/push/merge/rebase。唯一原用户修改仍为本Plan，已按任务授权维护证据索引。
- 最终精确入口 `LOCPATH=... BILIUP_REQUIRE_LOCALE_TEST=1 cargo test --locked -p danmaku-factory-sys -p danmaku-factory` **69通过/0失败**（54库单测、9错误、2Golden、1Locale/句柄宿主、3sys）；日志 `core-final-tests.txt`。CLI最终 `--no-deps` Clippy **exit0**，97项既有lint，本次新增lint已修复，日志 `cli-final-clippy.txt`。`test.yml` 添加当前迁移分支push触发条件；授权推送后即可实际启动三平台矩阵，当前尚未推送或运行。

### Gate 5：Linux行为/性能部分通过，Windows/macOS实际结果缺失

三平台CI配置已具备，但**没有当前代码的Windows/macOS通过记录**。本地分支未存在于远端，当前代码未提交；任务明确要求未授权不得commit/push。因此需要用户授权将这一可审查变更送到测试分支并执行矩阵，或提供对应平台执行环境。没有以“配置CI”替代“执行通过”。

### Gate 6：未执行，前置门禁未满足

`danmaku-factory-sys`、vendored C、PCRE2、C ABI、补丁和参考CI全部保留，等待Gate5实际跨平台结果。生产Rust已经不依赖它们；禁止据此把迁移全部完成或删除参考。跨平台通过后仍需执行原第6节的C退出、引用/锁/发布/许可证最终清理及清理后的完整验收；全仓既有格式失败也须在最终门禁中明确解决。

## 10. GitHub 集成与跨平台执行（2026-10-16 继续）

本轮用户明确授权在 `MostlyHarmlessxyz/biliup` 内 Commit、Push、PR、CI 修复及通过门禁后的常规 Merge，替代前轮禁止写入的限制。用户另确认：先用独立先导 PR 集成当前基线依赖，再让 Rust PR 保持独立范围；最终还需整理提交上游的 PR，不直接向上游推送或合并。

- 实际 Fork 为 **public**（GitHub API `isPrivate=false`），默认分支 `master@851ef03c80216ae24c7c6907b0832112b5dc13af`，Actions 已启用；未修改可见性、Token、Secrets 或仓库保护。
- 当前基线 `76d0306` 与 Fork master 的共同祖先为 `a3095c3`；当前基线另有33个既有提交、371个文件的渲染/worker/UI等依赖。用户授权独立先导 PR，避免将这些提交隐含混入迁移 PR。历史完整 PCRE2 Rust 移植 `aa51673` 不在本次分支祖先内。
- 上次 PR #1 于2026-10-09 10:42 UTC 合并，Test/CI/Docs 成功；Docker run `37919206850` 的构建与容器检查成功，amd64/arm64推送 `ghcr.io/biliup/caution` 失败，实际报错 `permission_denied: The requested installation does not exist`。该硬编码已存在于合并前父提交，属于Fork写入上游GHCR命名空间的权限配置问题，非Rust编译/测试失败。修复在Fork使用小写本仓库镜像路径，上游 `biliup/biliup` 自动保留原 `ghcr.io/biliup/caution`；不替换任何Token。
- 现有workflow未执行cargo fmt，17个历史格式差异没有导致该次Docker失败；本轮将以独立纯格式化commit解决，并保留格式检查门禁。
- Windows checkout必须保留原Golden及独立ASS参考字节；仅为这些冻结资产增加 `.gitattributes -text`，不修改Expected内容。Test的push/PR同分支运行使用concurrency去重，保证最新提交实际执行。
- 本轮核对原始证据：本地 `workspace-final-summary.json` 为1584/0/9，基准生产源码hash与最终源码一致，Secrets/凭据候选扫描无命中；后续以实际GitHub每个SHA的结果更新Gate5状态。

首轮远端执行：先导 PR 为 #2（`master ← integration/render-worker-prerequisites`）；迁移 Draft PR 为 #3（先堆叠于先导分支，先导合并后再切到 master）。迁移 `b9455087b7c3a09208ee6bdda7594d77bbc9e1c1` 的 Test run `38912214719` 实际启动三平台，Windows job `117011216103` 的54项核心单测通过，但 errors 中的 `long_paths_on_windows` 在最终 publish 报 Win32 error3，后续测试因此未执行，不能记为 Gate5 通过。

根因核对至 tempfile 3.27.0 Windows 实现：创建文件走 Rust 路径处理，persist 则直接向 SetFileAttributesW/MoveFileExW 传入路径。修复仅在 Windows 将已存在的父目录 canonicalize 为扩展长度路径，再分别创建临时文件和无覆盖发布不存在的目标；ASS 和 worker JSON 响应同时处理。保留原长路径断言，并增加长 Unicode 目录的真实 worker/ASS/JSON/句柄释放回归；等待修复提交的真实 Windows 重跑。17个历史格式文件已独立提交为 `832f6a0`，全 workspace fmt 已通过，并补上 CI 检查。
