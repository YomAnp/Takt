import { describe, expect, it } from "vitest";
import {
  clock,
  duration,
  eventTime,
  localInput,
} from "../../src/shared/lib/time";

describe("attendance time display", () => {
  it("retains total hours over midnight and distinguishes an unknown total", () => {
    expect(duration(25 * 3600 + 30 * 60, true)).toBe("25:30:00");
    expect(duration(null)).toBe("—");
    expect(duration(0)).toBe("00:00");
  });
  it("uses the server time zone instead of the phone time zone", () => {
    expect(localInput("2026-10-27T06:00:00Z", "Europe/Moscow")).toBe(
      "2026-10-27T09:00",
    );
    expect(eventTime("2026-10-27T09:00", "Europe/Moscow")).toBe(
      "2026-10-27T06:00:00.000Z",
    );
    expect(clock("2026-10-27T06:00:00Z", "Europe/Moscow")).toBe("09:00");
  });
  it("rejects nonexistent local time instead of silently moving an event", () => {
    expect(() => eventTime("2026-03-29T02:30", "Europe/Berlin")).toThrow();
    expect(() => eventTime("", "Europe/Moscow")).toThrow();
  });
});
