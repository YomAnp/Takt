import type {
  AccessChange,
  CheckoutPreview,
  LoginOutput,
  Preferences,
  Profile,
  ScheduledCalculationOutput,
  StateOutput,
  TimeCommand,
} from "./generated/types.gen";

export type {
  AccessChange,
  CheckoutPreview,
  Preferences,
  Profile,
  StateOutput,
  TimeCommand,
};
export type Summary = ScheduledCalculationOutput;
let token = "";
export const setToken = (value: string) => {
  token = value;
};

export class ApiError extends Error {
  constructor(
    public code: string,
    public status = 0,
  ) {
    super(code);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch("/api/v1" + path, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(
        body?.detail?.code ?? "request_failed",
        response.status,
      );
    }
    return response.status === 204 ? (undefined as T) : await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("connection_failed");
  } finally {
    clearTimeout(timeout);
  }
}
export const login = async (initData: string) => {
  const result = await api<LoginOutput>("/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ init_data: initData }),
  });
  setToken(result.token);
  return result.profile;
};
const messages: Record<string, string> = {
  connection_failed: "Нет связи с сервером. Проверьте подключение и повторите.",
  invalid_telegram_data: "Откройте приложение заново из меню бота.",
  login_required:
    "Сессия закончилась. Откройте приложение заново из меню бота.",
  account_disabled: "Доступ приостановлен. Обратитесь к администратору.",
  telegram_not_configured:
    "Вход через Telegram не настроен. Обратитесь к администратору.",
  stale_revision:
    "Данные уже изменились. Обновите день и подтвердите действие ещё раз.",
  already_present: "Приход уже отмечен. Обновите день.",
  event_in_future: "Время отметки не может быть в будущем.",
  event_before_latest_entry:
    "Это время раньше последней отметки. Проверьте выбранное время.",
  end_must_follow_start:
    "Уход должен быть позже прихода и начала текущего перерыва.",
  later_attendance_exists:
    "После этого ухода уже был новый приход. Отменить его нельзя.",
  protected_account: "Свою учётную запись и владельца нельзя менять здесь.",
  owner_required: "Назначать администраторов может только владелец.",
  admin_required: "Доступно только администратору.",
};
export const errorText = (error: unknown) =>
  messages[error instanceof ApiError ? error.code : ""] ??
  "Действие не выполнено. Проверьте данные и повторите.";
