import { useQuery } from "@tanstack/react-query";
import { api, errorText, type Summary } from "../../shared/api/client";
import { duration } from "../../shared/lib/time";
import { Notice } from "../../shared/ui/Notice";
export function Statistics() {
  const query = useQuery({
    queryKey: ["history"],
    queryFn: () => api<Array<Summary | null>>("/me/history"),
  });
  if (query.isPending)
    return (
      <p className="muted" role="status">
        Загружаем статистику…
      </p>
    );
  if (query.error) return <Notice>{errorText(query.error)}</Notice>;
  const days = (query.data || []).filter(
    (value): value is Summary => value !== null && "total_seconds" in value,
  );
  const closed = days.filter((day) => !day.is_provisional);
  const total = closed.reduce((sum, day) => sum + (day.total_seconds || 0), 0);
  const overtime = closed.reduce(
    (sum, day) => sum + (day.overtime_seconds || 0),
    0,
  );
  const maximum = Math.max(3600, ...days.map((day) => day.total_seconds || 0));
  return (
    <section className="statistics">
      <p className="muted">Последние 7 дней</p>
      <h1>Моё время</h1>
      <div className="stat-overview">
        <div>
          <strong>{duration(total)}</strong>
          <span>всего</span>
        </div>
        <div>
          <strong>{duration(overtime)}</strong>
          <span>после окончания</span>
        </div>
      </div>
      <p className="caption">
        Итоги по завершённым дням. Открытый день показан отдельно.
      </p>
      <div className="week-chart" aria-label="Время по дням">
        {[...days].reverse().map((day) => (
          <div key={day.work_date}>
            <div
              className={"bar " + (day.is_provisional ? "provisional" : "")}
              style={{
                height: Math.max(3, ((day.total_seconds || 0) / maximum) * 120),
              }}
            />
            <span>
              {new Intl.DateTimeFormat("ru", { weekday: "short" }).format(
                new Date(day.work_date + "T12:00:00"),
              )}
            </span>
          </div>
        ))}
      </div>
      <div className="history">
        {days.map((day) => (
          <div className="history-row" key={day.work_date}>
            <div>
              <strong>
                {new Intl.DateTimeFormat("ru", {
                  day: "numeric",
                  month: "long",
                }).format(new Date(day.work_date + "T12:00:00"))}
              </strong>
              <span>
                {day.state === "needs_checkout"
                  ? "Уточните уход"
                  : day.is_provisional
                    ? "День продолжается"
                    : day.total_seconds
                      ? "День завершён"
                      : "Без отметок"}
              </span>
            </div>
            <strong>{duration(day.total_seconds)}</strong>
          </div>
        ))}
      </div>
      {!days.length && (
        <p className="empty-copy">
          Здесь появится ваша статистика после первого рабочего дня.
        </p>
      )}
    </section>
  );
}
