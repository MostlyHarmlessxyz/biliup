/* Gate 0 executable specification of the *defined* C time conversions.
 * cc -std=c11 -ffp-contract=off -I crates/danmaku-factory-sys/vendor/DanmakuFactory/src \
 *   crates/danmaku-factory/tests/baseline/time.c -o target/danmaku-time
 */
#include "Define/DanmakuDef.h"
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    const char *seconds[] = {
        "-0.00009", "0", "0.000049", "0.0001", "0.0004999", "0.0005",
        "0.0015", "1.001", "1.004", "1.005", "1.0145", "12345.6785",
        "900000.001", "1800000.001", "2147470"
    };
    puts("[");
    for (unsigned i = 0; i < sizeof(seconds) / sizeof(seconds[0]); i++) {
        float value = (float)atof(seconds[i]);
        if (value < EPS) value = 0;
        int ms = GET_MS_FLT(value);
        printf("  {\"seconds\":\"%s\",\"source_time_ms\":%d,\"ass_start_ms\":%d}%s\n",
               seconds[i], ms, GET_ASS_MS_INT(ms),
               i + 1 == sizeof(seconds) / sizeof(seconds[0]) ? "" : ",");
    }
    puts("]");
    return 0;
}
