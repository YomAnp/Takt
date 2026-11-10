# Friends, smoking breaks, and rankings

[Home](../index.md) · [Русский](../../ru/product/people.md)

The People section brings together friends and confirmed-hour rankings. Detailed personal entries remain available to the employee and administrators.

## Friends

A user shares a personal bot link. The recipient opens the app, reviews the invitation, and sends a request. Friendship starts when the other party accepts. Opening a link does not add anyone automatically.

A link lasts 7 days. Repeated requests retain the active link; expiry produces a new one. Users can have up to 20 outgoing requests and send at most 20 new requests within 24 hours. Cancellation does not reset the limit. After rejection, the same pair can try again after 24 hours.

Friends can see the name, available photo, recorded work status, and total confirmed hours. They cannot access arrival and departure history or personal preferences. Requests can be accepted, declined, or cancelled; friends can be removed. Accounts disabled by an administrator are hidden from lists.

## Status and smoking breaks

Working, On break, and Smoking reflect saved entries. They do not mean the person is currently looking at the screen or online.

The smoking-break action starts a break of kind `smoke`. An ordinary break has kind `regular`. Only one break can remain open; Return closes it. Smoking breaks count toward total attendance and do not move the working-day end time.

On return, the app reads current server state. Departure closes an open smoking break together with attendance; undo restores both. If a previous day remains open, the status asks for corrected entries rather than showing an active smoking break.

Statuses refresh after actions and on returning to the app. The visible People section uses limited periodic polling, which stops while the app is hidden. The last refresh time is not treated as proof of presence.

## Rankings

Participation in the public ranking is optional. It is disabled by default, including for existing accounts. Turning it off removes the user from the public list. The friends ranking is available within accepted friendships and includes the user themselves.

| Period | Included days |
| --- | --- |
| Week | From Monday of the current week |
| 30 days | Today and the preceding 29 days |
| All time | The complete history of confirmed intervals |

Only closed attendance intervals contribute, including recorded breaks. Open intervals do not add unconfirmed hours. An interval crossing midnight belongs entirely to its arrival date, using the application's time zone.

Position follows the number of confirmed seconds. Equal totals share a rank, with a stable order within that group. The user's own position is returned separately even outside the current page. Lists load in pages of 30 people; an empty state appears before any confirmed time exists.
