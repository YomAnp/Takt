import { errorText } from "../../shared/api/client";
import { clock, duration } from "../../shared/lib/time";
import { Sheet } from "../../shared/ui/Sheet";
import { Notice } from "../../shared/ui/Notice";
import type { TimeAccounting } from "./useTimeAccounting";

export function TimeDialog({ account }: { account: TimeAccounting }) {
  const {
    data,
    serverNow,
    zone,
    pending,
    send,
    mutation,
    failed,
    dialog,
    custom,
    setCustom,
    chosen,
    setChosen,
    preview,
    localError,
    setLocalError,
    previewMutation,
    prepareFinish,
    pickedTime,
    setDialog,
    setPreview,
  } = account;
  if (!dialog) return null;
  return (
    <Sheet
      title={
        dialog === "start"
          ? "Начать рабочий день"
          : dialog === "recover"
            ? "Уточнить время ухода"
            : "Завершить рабочий день"
      }
      close={() => {
        if (!mutation.isPending) setDialog(null);
      }}
    >
      {!preview ? (
        <>
          <p className="muted">
            {dialog === "start"
              ? "Пришли раньше? Укажите фактическое время — учёт начнётся с него."
              : "Укажите, когда вы ушли. Перед сохранением покажем итог."}
          </p>
          <div className="time-options">
            <button
              className={!custom ? "chosen" : ""}
              disabled={dialog === "recover" && !pending?.can_use_scheduled_end}
              onClick={() => setCustom(false)}
            >
              {dialog === "recover" ? "По окончанию дня" : "Сейчас"}
              <strong>
                {dialog === "recover"
                  ? pending?.scheduled_end_at
                    ? clock(pending.scheduled_end_at, zone)
                    : "—"
                  : data
                    ? clock(serverNow, zone)
                    : "—"}
              </strong>
            </button>
            <button
              className={custom ? "chosen" : ""}
              onClick={() => setCustom(true)}
            >
              Указать время
              <strong>
                {dialog === "start" ? "Пришёл раньше" : "Фактический уход"}
              </strong>
            </button>
          </div>
          {dialog === "recover" && !pending?.can_use_scheduled_end && (
            <p className="caption">
              После окончания есть другие отметки. Укажите фактическое время
              ухода.
            </p>
          )}
          {custom && (
            <label>
              Дата и время ({zone})
              <input
                type="datetime-local"
                required
                value={chosen}
                onChange={(event) => setChosen(event.target.value)}
              />
            </label>
          )}
          <button
            className="primary"
            disabled={
              mutation.isPending ||
              previewMutation.isPending ||
              !!failed ||
              (dialog === "recover" &&
                !custom &&
                !pending?.can_use_scheduled_end)
            }
            onClick={() => {
              if (dialog === "start") {
                try {
                  send("check_in", { occurred_at: pickedTime() });
                } catch (error) {
                  setLocalError((error as Error).message);
                }
              } else prepareFinish();
            }}
          >
            {mutation.isPending || previewMutation.isPending
              ? "Сохраняем…"
              : dialog === "start"
                ? "Отметить приход"
                : "Посмотреть итог"}
          </button>
        </>
      ) : (
        <>
          <p className="muted">Уход в {clock(preview.proposed_end_at, zone)}</p>
          <div className="departure-total">
            <span>Общее время</span>
            <strong>
              {duration(
                "total_seconds" in preview.summary
                  ? preview.summary.total_seconds
                  : preview.summary.credited_seconds,
              )}
            </strong>
          </div>
          {preview.will_end_break && (
            <p className="muted">
              Текущий перерыв завершится вместе с рабочим днём. Он входит в
              общее время.
            </p>
          )}
          <button
            className="primary"
            disabled={mutation.isPending || !!failed}
            onClick={() =>
              send("check_out", {
                attendance_id: preview.attendance.id,
                expected_revision: preview.attendance.revision,
                occurred_at: preview.proposed_end_at,
                confirmed: true,
              })
            }
          >
            {mutation.isPending ? "Сохраняем…" : "Подтвердить уход"}
          </button>
          <button
            className="text-button"
            disabled={mutation.isPending}
            onClick={() => {
              setPreview(null);
              mutation.reset();
            }}
          >
            Другое время
          </button>
        </>
      )}
      {localError && <Notice>{localError}</Notice>}
      {previewMutation.error && (
        <Notice>{errorText(previewMutation.error)}</Notice>
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
    </Sheet>
  );
}
