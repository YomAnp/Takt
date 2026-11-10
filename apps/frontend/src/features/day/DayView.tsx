import {
  CalendarDays,
  ChevronDown,
  Cigarette,
  Coffee,
  LogOut,
  Play,
  Undo2,
} from "lucide-react";
import {
  errorText,
  type Profile,
  type StateOutput,
} from "../../shared/api/client";
import { clock, duration } from "../../shared/lib/time";
import { Notice } from "../../shared/ui/Notice";
import type { TimeAccounting } from "./useTimeAccounting";

export function DayView({
  profile,
  account,
}: {
  profile: Profile;
  account: TimeAccounting;
}) {
  const {
    state,
    data,
    zone,
    summary,
    current,
    pause,
    pending,
    total,
    lastToday,
    extraLive,
    live,
    busy,
    open,
    send,
    mutation,
    failed,
    serverNow,
  } = account;
  const smoking = pause && "kind" in pause && pause.kind === "smoke";
  const status = state.isPending
    ? "Загружаем день"
    : pause
      ? smoking
        ? "На перекуре"
        : "На перерыве"
      : current
        ? "На работе"
        : total > 0
          ? "День завершён"
          : "День не начат";
  const activeBreakSeconds = pause
    ? Math.max(
        0,
        Math.floor(
          (Date.parse(serverNow) - Date.parse(pause.started_at)) / 1000,
        ),
      )
    : 0;
  return (
    <section className="day" aria-labelledby="day-title">
      <div className="screen-heading">
        <h1 id="day-title">Мой день</h1>
        <span className="date-chip">
          {new Intl.DateTimeFormat("ru", {
            day: "numeric",
            month: "long",
            timeZone: zone,
          }).format(new Date(data?.now || Date.now()))}
        </span>
      </div>
      {state.error && (
        <Notice>
          {errorText(state.error)}{" "}
          <button className="text-button" onClick={() => state.refetch()}>
            Обновить
          </button>
        </Notice>
      )}
      {pending ? (
        <div className="recovery">
          <h2>Остался незавершённый день</h2>
          <p>
            Уточните уход за{" "}
            {new Intl.DateTimeFormat("ru", {
              day: "numeric",
              month: "long",
            }).format(new Date(pending.work_date + "T12:00:00"))}
            , чтобы начать сегодняшний.
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => open("recover")}
          >
            Указать время ухода
          </button>
        </div>
      ) : (
        <>
          <div className={"time-summary " + (current ? "is-working" : "")}>
            <div className="clock-face" aria-label="Учёт времени сегодня">
              <div
                className={"presence-status " + (pause ? "break-status" : "")}
              >
                <span className={"status-dot " + (!current ? "quiet" : "")} />
                {smoking && <Cigarette aria-hidden="true" size={15} />}
                <span>{status}</span>
              </div>
              <strong
                className="attendance-time"
                aria-label="Общее время присутствия"
              >
                {state.isPending && !data ? "—" : duration(total, true)}
              </strong>
              <span className="clock-caption">
                {current
                  ? "учтено сегодня"
                  : total > 0
                    ? "время сохранено"
                    : "до начала дня"}
              </span>
              <div className="time-meta">
                <span>Сегодня</span>
                <span>
                  До <strong>{profile.end_time?.slice(0, 5)}</strong>
                </span>
              </div>
            </div>
          </div>
          <button
            className="primary main-action"
            disabled={busy || !data || !!state.error}
            onClick={() => open(current ? "finish" : "start")}
          >
            {current ? (
              <LogOut aria-hidden="true" size={20} />
            ) : (
              <Play aria-hidden="true" size={20} />
            )}
            <span>{current ? "Завершить день" : "Отметиться"}</span>
          </button>
          {current && (
            <div
              className={"break-controls " + (pause ? "has-active-break" : "")}
            >
              {pause ? (
                <button
                  className="break-action"
                  disabled={busy}
                  onClick={() => send("end_break", { break_id: pause.id })}
                >
                  {smoking ? (
                    <Cigarette aria-hidden="true" size={19} />
                  ) : (
                    <Coffee aria-hidden="true" size={19} />
                  )}
                  <span>
                    Вернуться
                    {activeBreakSeconds ? (
                      <small>
                        {duration(activeBreakSeconds)} на{" "}
                        {smoking ? "перекуре" : "перерыве"}
                      </small>
                    ) : null}
                  </span>
                </button>
              ) : (
                <>
                  <button
                    className="break-action"
                    disabled={busy}
                    onClick={() => send("start_break")}
                  >
                    <Coffee aria-hidden="true" size={18} />
                    Перерыв
                  </button>
                  <button
                    className="break-action"
                    disabled={busy}
                    onClick={() => send("start_break", { break_kind: "smoke" })}
                  >
                    <Cigarette aria-hidden="true" size={18} />
                    На перекур
                  </button>
                </>
              )}
            </div>
          )}
          {summary && (
            <div className="day-details">
              <span>
                Перерывы{" "}
                <strong>
                  {duration((summary.break_seconds || 0) + (pause ? live : 0))}
                </strong>
              </span>
              <span>
                После окончания{" "}
                <strong>
                  {duration((summary.overtime_seconds || 0) + extraLive)}
                </strong>
              </span>
            </div>
          )}
        </>
      )}
      {mutation.error && <Notice>{errorText(mutation.error)}</Notice>}
      {failed && (
        <button
          className="secondary"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate(failed)}
        >
          Повторить то же действие
        </button>
      )}
      <details className="day-journal">
        <summary>
          <span>{pending ? "Незавершённый день" : "Отметки дня"}</span>
          <ChevronDown aria-hidden="true" size={18} />
        </summary>
        {current || lastToday ? (
          <Timeline record={current || lastToday!} zone={zone} />
        ) : (
          <div className="empty-journal">
            <CalendarDays aria-hidden="true" size={19} />
            <p>Здесь появятся приход, перерывы и уход.</p>
          </div>
        )}
        {!current && data?.last_finished && (
          <button
            className="text-button undo-action"
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  "Отменить последний уход и продолжить этот день?",
                )
              )
                send("reopen", {
                  attendance_id: data.last_finished!.id,
                  expected_revision: data.last_finished!.revision,
                });
            }}
          >
            <Undo2 aria-hidden="true" size={17} />
            Отменить последний уход
          </button>
        )}
      </details>
      <p className="quiet-note">Перерывы входят в общее время.</p>
    </section>
  );
}
function Timeline({
  record,
  zone,
}: {
  record: NonNullable<StateOutput["attendance"]>;
  zone: string;
}) {
  const events = [
    { time: record.started_at, label: "Приход", kind: "arrival" },
    ...record.breaks.flatMap((item) => [
      {
        time: item.started_at,
        label:
          "kind" in item && item.kind === "smoke" ? "На перекур" : "Перерыв",
        kind: "break",
      },
      ...(item.ended_at
        ? [{ time: item.ended_at, label: "Вернулся", kind: "break" }]
        : []),
    ]),
    ...(record.ended_at
      ? [{ time: record.ended_at, label: "Уход", kind: "departure" }]
      : []),
  ];
  return (
    <ol className="timeline">
      {events.map((event, index) => (
        <li key={index}>
          <time>{clock(event.time, zone)}</time>
          <span className={"event-dot " + event.kind} />
          <span>{event.label}</span>
        </li>
      ))}
    </ol>
  );
}
