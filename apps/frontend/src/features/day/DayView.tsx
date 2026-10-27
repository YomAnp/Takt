import {
  ArrowRight,
  CalendarDays,
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
  } = account;
  return (
    <section className="day">
      <div className="day-heading">
        <div>
          <p className="greeting">
            Здравствуйте, {profile.display_name.split(" ")[0]}
          </p>
          <h1>Мой день</h1>
        </div>
        <span className="date-chip">
          {new Intl.DateTimeFormat("ru", {
            day: "numeric",
            month: "short",
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
          <span className="status-dot amber" />
          <h2>Когда закончился прошлый день?</h2>
          <p>
            Уход за{" "}
            {new Intl.DateTimeFormat("ru", {
              day: "numeric",
              month: "long",
            }).format(new Date(pending.work_date + "T12:00:00"))}{" "}
            не отмечен. Уточните время, и можно начинать новый день.
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => open("recover")}
          >
            Указать время ухода
            <ArrowRight size={18} />
          </button>
        </div>
      ) : (
        <>
          <div className={"presence-status " + (pause ? "break-status" : "")}>
            <span className={"status-dot " + (!current ? "quiet" : "")} />
            {state.isPending
              ? "Загружаем день"
              : pause
                ? "На перерыве"
                : current
                  ? "На работе"
                  : total > 0
                    ? "День завершён"
                    : "Всё готово к началу"}
          </div>
          <div className={"clock-face " + (current ? "active" : "")}>
            {Array.from({ length: 12 }, (_, index) => (
              <i
                className="clock-tick"
                style={{ transform: "rotate(" + index * 30 + "deg)" }}
                key={index}
              />
            ))}
            <div className="clock-content">
              <span>Сегодня</span>
              <strong aria-label="Общее время присутствия">
                {duration(total, true)}
              </strong>
              <span>
                {current
                  ? "день продолжается"
                  : total > 0
                    ? "время сохранено"
                    : "время для вашего дня"}
              </span>
            </div>
            <span className="dial-dot" />
          </div>
          <div className="end-time">
            <span>Окончание дня</span>
            <strong>{profile.end_time?.slice(0, 5)}</strong>
          </div>
          <button
            className="primary main-action"
            disabled={busy || !data || !!state.error}
            onClick={() => open(current ? "finish" : "start")}
          >
            {current ? <LogOut size={20} /> : <Play size={20} />}
            <span>{current ? "Завершить день" : "Отметиться"}</span>
          </button>
          {current && (
            <button
              className="break-action"
              disabled={busy}
              onClick={() =>
                send(
                  pause ? "end_break" : "start_break",
                  pause ? { break_id: pause.id } : {},
                )
              }
            >
              <Coffee size={18} />
              {pause ? "Вернуться с перерыва" : "Отметить перерыв"}
            </button>
          )}
          {!current && data?.last_finished && (
            <button
              className="break-action"
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
              <Undo2 size={16} />
              Отменить последний уход
            </button>
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
      <div className="day-journal">
        <div className="section-heading">
          <h2>Отметки дня</h2>
          <span>{current ? "Сохранены" : ""}</span>
        </div>
        {current || lastToday ? (
          <Timeline record={current || lastToday!} zone={zone} />
        ) : (
          <div className="empty-journal">
            <CalendarDays size={20} />
            <p>
              Отметьте приход, когда будете готовы.
              <br />
              <span>Можно указать, что пришли раньше.</span>
            </p>
          </div>
        )}
      </div>
      {summary && !pending && (
        <div className="day-details">
          <span>
            Перерывы{" "}
            <strong>
              {duration(
                (summary.break_seconds || 0) + (pause && !pending ? live : 0),
              )}
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
      <p className="quiet-note">
        Перерывы входят в общее время.
        <br />
        Отмечайте их, если хотите видеть в статистике.
      </p>
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
      { time: item.started_at, label: "Перерыв", kind: "break" },
      ...(item.ended_at
        ? [{ time: item.ended_at, label: "Перерыв завершён", kind: "break" }]
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
