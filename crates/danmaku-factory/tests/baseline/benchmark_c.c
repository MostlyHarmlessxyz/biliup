/* Benchmark-only bridge. The included, hash-verified frozen wrapper supplies
 * check_options/to_config and its original option/result structures. The
 * conversion algorithms are linked unchanged from the frozen core archives.
 * The pool is released separately so both engines measure destruction in the
 * cleanup phase, rather than including freeList only in C's core time. */
#include "df_ffi.c"
#include <stdint.h>
#include <sys/resource.h>

int benchmark_usage(uint64_t *user_us, uint64_t *system_us, uint64_t *peak_rss_bytes)
{
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0)
        return -1;
    *user_us = (uint64_t)usage.ru_utime.tv_sec * 1000000 + usage.ru_utime.tv_usec;
    *system_us = (uint64_t)usage.ru_stime.tv_sec * 1000000 + usage.ru_stime.tv_usec;
#if defined(__APPLE__)
    *peak_rss_bytes = usage.ru_maxrss;
#else
    *peak_rss_bytes = (uint64_t)usage.ru_maxrss * 1024;
#endif
    return 0;
}

int benchmark_c_core(const char *input, const char *output, const df_options *options,
                     void **owned_pool, df_result *result)
{
    memset(result, 0, sizeof(*result));
    result->struct_size = sizeof(*result);
    *owned_pool = NULL;
    const char *invalid = check_options(options);
    if (invalid != NULL)
        return fail(result, DF_ERR_INVALID_ARGUMENT, 0, 0, "invalid %s", invalid);
    const struct lconv *numeric = localeconv();
    if (numeric == NULL || numeric->decimal_point == NULL || strcmp(numeric->decimal_point, ".") != 0)
        return fail(result, DF_ERR_LOCALE, 0, 0, "LC_NUMERIC must use '.' as the decimal point");

    CONFIG config;
    to_config(options, &config);
    DANMAKU *pool = NULL;
    errno = 0;
    int code = readXml(input, &pool, "a", 0.0f, NULL);
    if (code != 0)
    {
        /* readXml already frees a failed list, as in the frozen wrapper. */
        return fail(result, DF_ERR_INPUT_READ, code, errno, "benchmark readXml returned %d", code);
    }
    for (DANMAKU *ptr = pool; ptr != NULL; ptr = ptr->next)
    {
        if (IS_SPECIAL(ptr) && ptr->special == NULL)
        {
            freeList(pool);
            return fail(result, DF_ERR_UNSUPPORTED_INPUT, 0, 0, "special danmaku without data");
        }
        result->danmaku_count++;
    }
    blockByType(pool, config.blockmode, NULL, config.blocklistRegexEnabled);
    normFontSize(pool, config);
    code = sortList(&pool, NULL);
    if (code == 0)
        code = writeAss(output, pool, config, NULL, NULL);
    if (code != 0)
    {
        freeList(pool);
        return fail(result, DF_ERR_INTERNAL, code, errno, "benchmark sort/write returned %d", code);
    }
    for (DANMAKU *ptr = pool; ptr != NULL; ptr = ptr->next)
        if (ptr->type < 0)
            result->blocked_count++;
    *owned_pool = pool;
    return DF_OK;
}

void benchmark_c_release(void *owned_pool)
{
    freeList(owned_pool);
}
