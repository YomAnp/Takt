# Time accounting

[Home](../index.md) · [Русский](../../ru/product/time-accounting.md)

A working day consists of explicitly recorded attendance intervals. Total attendance is the sum of their durations. Breaks remain part of that total; recording them is optional and serves personal statistics.

## Working-day end time

An employee saves a local end time, for example 18:00. It remains in effect until changed in settings. A new value applies to the current and subsequent days; past days retain their earlier rule. A break does not move the end time.

The ending is a reference point, not a command to close attendance. Attendance beyond it is calculated automatically, including breaks. Users do not enter overtime separately.

| Example | Total attendance | Breaks | Beyond the end |
| --- | --- | --- | --- |
| Arrival 09:00, departure 18:00, break 30 minutes, end time 18:00 | 9 hours | 30 minutes | 0 minutes |
| Arrival 09:00, departure 18:30, no break entries, end time 18:00 | 9 hours 30 minutes | 0 minutes | 30 minutes |

No break entries means there is no recorded break data. The application does not detect breaks on its own.

## Arrival and departure

Opening the application does not start accounting. “Check in” offers starting now or entering an earlier time: for example, opening at 10:00 can record arrival at 09:00. The entry retains the actual event time and the time it was recorded.

Before departure, the application shows the result for the selected time. If a break is open, confirmation explains that it will also end. Confirmation saves both entries. Undoing the latest departure restores attendance and only the break closed together with it. Undo is unavailable after a subsequent arrival.

Future events, overlaps, and departure before the latest entry are rejected. If another device changes the state, confirmation must be refreshed.

## Missed departure

When an attendance interval from a previous day remains open, returning to the application first asks for its ending. Users can confirm departure at that day's saved end time or enter the actual date and time. For example, departure at 19:15 with an end time of 18:00 adds 1 hour 15 minutes beyond the reference point.

The scheduled time cannot be selected if it precedes arrival or existing events. If a break began at 18:10, the application cannot finish the day at 18:00 and conceal that entry.

Until confirmation, the previous open day has the state `needs_checkout`. Its total, breaks, and time beyond the ending are returned as unknown instead of growing until the application is reopened. The sum of already closed intervals is available separately. A new arrival is possible after the open interval is closed.

An interval crossing midnight belongs entirely to the local arrival date. Arrival at 17:00 and departure at 02:00 the next day give 9 hours for the arrival day; with an end time of 18:00, 8 hours fall beyond the reference point. Those hours are not counted again on the following day.

## First launch and main screen

First launch introduces the application, offers a name that can be edited from Telegram's data, and asks for a working-day end time. After saving, users can record arrival now, enter an earlier time, or browse without starting attendance. These settings are not requested again on subsequent visits.

The main action follows the state: “Check in” or “Finish”. Total attendance and the end time sit together; optional break controls receive less emphasis. Detailed statistics, people, and settings do not crowd the main screen. Recovery of a missed departure appears before an invitation to start a new day.

The interface is designed for phones, short actions, and reopening Telegram. The timer updates locally from the latest server response; state is refreshed on return or after an action. On a network error, an action is not treated as saved without confirmation. Retrying uses the same identifier and creates no second entry.

Short application reactions use real data and confirmed totals. They do not delay entry or encourage longer attendance for rewards.
