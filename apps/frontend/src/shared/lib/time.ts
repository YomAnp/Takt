export function duration(
  seconds: number | null | undefined,
  withSeconds = false,
): string {
  if (seconds == null) return "—";
  const value = Math.max(0, Math.floor(seconds));
  const h = Math.floor(value / 3600)
    .toString()
    .padStart(2, "0");
  const m = Math.floor((value / 60) % 60)
    .toString()
    .padStart(2, "0");
  return (
    h +
    ":" +
    m +
    (withSeconds ? ":" + (value % 60).toString().padStart(2, "0") : "")
  );
}
export function clock(value: string, zone = "Europe/Moscow"): string {
  return new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: zone,
  }).format(new Date(value));
}
export function localInput(value: string, zone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const p = (key: string) => parts.find((part) => part.type === key)?.value;
  return (
    p("year") +
    "-" +
    p("month") +
    "-" +
    p("day") +
    "T" +
    p("hour") +
    ":" +
    p("minute")
  );
}
export function eventTime(value: string, zone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))
    throw new Error("Укажите дату и время.");
  const intended = Date.parse(value + ":00Z");
  let actual = intended;
  for (let index = 0; index < 3; index++) {
    const represented = Date.parse(
      localInput(new Date(actual).toISOString(), zone) + ":00Z",
    );
    actual += intended - represented;
  }
  const iso = new Date(actual).toISOString();
  if (localInput(iso, zone) !== value)
    throw new Error("Это местное время недоступно. Укажите другое.");
  return iso;
}
