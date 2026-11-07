// Compile-time constants. Everything that may change per site or per board is a
// runtime setting instead (src/settings.cpp), editable from the serial console,
// the setup portal or /config/settings.txt on the SD card.
#pragma once

#define FW_VERSION "0.1.0"
#define CSV_SCHEMA 1            // bump when the meaning of the CSV columns changes

#define MAX_METERS 4            // meters per logger on the RS485 bus
#define MAX_REGS 32             // values read per meter (register table lines)
#define RAM_QUEUE_ROWS 180      // rows kept in RAM when the SD card has failed (3 h)

#define TIME_VALID_AFTER 1735689600L   // 2025-01-01: anything earlier means "clock not set"

#define WDT_TIMEOUT_S 60        // task watchdog: a task stuck this long reboots the board
#define STABLE_UPTIME_S 600     // after 10 min up, the boot is "stable" (boot-loop and OTA rollback logic)
#define BOOTLOOP_LIMIT 5        // unstable boots in a row before safe mode
#define HTTP_TIMEOUT_MS 15000
#define LIVE_TIMEOUT_MS 5000
#define MAX_BATCH_BYTES 24000   // upload body limit per POST
#define CATCHUP_BATCHES 20      // batches sent back to back when there is a backlog

// SD card layout (same day-file layout as the server, see docs/DATA-FORMAT.md)
#define DIR_DATA "/data"         // /data/YYYY/MM/YYYY-MM-DD.csv (UTC days)
#define DIR_LOG "/log"           // /log/YYYY-MM.log event log
#define FILE_UPLOAD_PTR "/state/upload.txt"
#define FILE_SETTINGS_IMPORT "/config/settings.txt"
#define FILE_REGISTERS "/config/registers.csv"
