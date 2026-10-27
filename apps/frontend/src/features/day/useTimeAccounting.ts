import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type CheckoutPreview,
  type Profile,
  type StateOutput,
  type Summary,
  type TimeCommand,
} from "../../shared/api/client";
import { eventTime, localInput } from "../../shared/lib/time";
type Operation =
  "check_in" | "check_out" | "start_break" | "end_break" | "reopen";
type Dialog = "start" | "finish" | "recover" | null;
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20)
  );
}

export function useTimeAccounting(
  profile: Profile | null,
  setAnnouncement: (value: string) => void,
) {
  const cache = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [custom, setCustom] = useState(false);
  const [chosen, setChosen] = useState("");
  const [localError, setLocalError] = useState("");
  const [preview, setPreview] = useState<CheckoutPreview | null>(null);
  const [tick, setTick] = useState(Date.now());
  const [anchor, setAnchor] = useState(Date.now());
  const [failed, setFailed] = useState<{
    operation: Operation;
    body: TimeCommand;
  } | null>(null);
  const state = useQuery({
    queryKey: ["state"],
    queryFn: () => api<StateOutput>("/me/state"),
    enabled: !!profile?.onboarded,
    refetchOnReconnect: true,
  });
  useEffect(() => {
    setAnchor(Date.now());
  }, [state.data]);
  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible")
        cache.invalidateQueries({ queryKey: ["state"] });
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [cache]);
  const mutation = useMutation({
    mutationFn: ({
      operation,
      body,
    }: {
      operation: Operation;
      body: TimeCommand;
    }) =>
      api("/me/attendance/" + operation, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (_result, variables) => {
      setDialog(null);
      setPreview(null);
      setFailed(null);
      setLocalError("");
      setAnnouncement(
        variables.operation === "check_in"
          ? "Приход отмечен"
          : variables.operation === "check_out"
            ? "День завершён"
            : variables.operation === "reopen"
              ? "Уход отменён"
              : variables.operation === "start_break"
                ? "Перерыв отмечен"
                : "Перерыв завершён",
      );
      cache.invalidateQueries({ queryKey: ["state"] });
      cache.invalidateQueries({ queryKey: ["history"] });
    },
    onError: (error, variables) => {
      if (error instanceof ApiError && error.code === "stale_revision")
        setPreview(null);
      setFailed(
        error instanceof ApiError && (error.status === 0 || error.status >= 500)
          ? variables
          : null,
      );
      cache.invalidateQueries({ queryKey: ["state"] });
    },
  });
  const previewMutation = useMutation({
    mutationFn: (body: { attendance_id: string; occurred_at?: string }) =>
      api<CheckoutPreview>("/me/attendance/preview", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: setPreview,
  });
  const data = state.data;
  const zone = data?.time_zone || "Europe/Moscow";
  const summary =
    data?.summary && "total_seconds" in data.summary
      ? (data.summary as Summary)
      : null;
  const current = data?.attendance;
  const pause = current?.breaks.find((item) => item.ended_at === null);
  const pending = data?.pending;
  const live =
    current && !pending ? Math.max(0, Math.floor((tick - anchor) / 1000)) : 0;
  const total =
    summary?.total_seconds == null ? 0 : summary.total_seconds + live;
  const lastToday =
    data?.last_finished &&
    summary &&
    localInput(data.last_finished.started_at, zone).slice(0, 10) ===
      summary.work_date
      ? data.last_finished
      : null;
  const extraLive =
    current && !pending && summary && data
      ? Math.max(
          0,
          Math.floor(
            (Date.parse(data.now) +
              live * 1000 -
              Math.max(
                Date.parse(data.now),
                Date.parse(summary.scheduled_end_at),
              )) /
              1000,
          ),
        )
      : 0;
  const serverNow = data
    ? new Date(Date.parse(data.now) + Math.max(0, tick - anchor)).toISOString()
    : new Date().toISOString();
  const refreshedDate = useRef("");
  useEffect(() => {
    if (!data) return;
    const date = localInput(serverNow, zone).slice(0, 10);
    if (
      date !== localInput(data.now, zone).slice(0, 10) &&
      refreshedDate.current !== date
    ) {
      refreshedDate.current = date;
      cache.invalidateQueries({ queryKey: ["state"] });
    }
  }, [serverNow, zone, data, cache]);
  const busy = mutation.isPending || state.isFetching || !!failed;

  function open(kind: Dialog) {
    setDialog(kind);
    setCustom(false);
    setPreview(null);
    setLocalError("");
    mutation.reset();
    previewMutation.reset();
    setChosen(localInput(serverNow, zone));
  }
  function send(operation: Operation, extra: Partial<TimeCommand> = {}) {
    if (mutation.isPending || failed) return;
    mutation.mutate({
      operation,
      body: {
        request_id: requestId(),
        ...(operation !== "check_in"
          ? { attendance_id: current?.id, expected_revision: current?.revision }
          : {}),
        ...extra,
      },
    });
  }
  function pickedTime() {
    if (dialog === "recover" && !custom)
      return pending?.scheduled_end_at || undefined;
    return custom ? eventTime(chosen, zone) : undefined;
  }
  function prepareFinish() {
    try {
      setLocalError("");
      previewMutation.mutate({
        attendance_id: current!.id,
        occurred_at: pickedTime(),
      });
    } catch (error) {
      setLocalError((error as Error).message);
    }
  }

  return {
    state,
    serverNow,
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
  };
}
export type TimeAccounting = ReturnType<typeof useTimeAccounting>;
