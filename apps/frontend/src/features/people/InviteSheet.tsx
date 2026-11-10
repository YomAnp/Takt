import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Check, Copy, Send } from "lucide-react";
import { api, errorText } from "../../shared/api/client";
import { Sheet } from "../../shared/ui/Sheet";
import { Notice } from "../../shared/ui/Notice";
import { Avatar } from "../../shared/ui/Avatar";
import { haptic } from "../../shared/lib/telegram";
import type { Invite, InvitePreview, RequestResult } from "./types";

export function InviteShare({ close }: { close(): void }) {
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const query = useQuery({
    queryKey: ["invite-link"],
    queryFn: () => api<Invite>("/social/invite", { method: "POST" }),
    staleTime: 60_000,
    retry: 1,
  });
  async function copy() {
    if (!query.data) return;
    try {
      await navigator.clipboard.writeText(query.data.url);
      setCopied(true);
      haptic("success");
    } catch {
      input.current?.select();
    }
  }
  function share() {
    if (!query.data) return;
    const url =
      "https://t.me/share/url?url=" + encodeURIComponent(query.data.url);
    const app = window.Telegram?.WebApp;
    if (app?.openTelegramLink) app.openTelegramLink(url);
    else window.open(url, "_blank", "noopener,noreferrer");
  }
  return (
    <Sheet title="Пригласить друга" close={close}>
      <p className="muted">
        Отправьте ссылку в Telegram. Дружба появится после подтверждения заявки.
      </p>
      {query.isPending && <p role="status">Готовим ссылку…</p>}
      {query.error && (
        <Notice>
          {errorText(query.error)}{" "}
          <button className="text-button" onClick={() => query.refetch()}>
            Повторить
          </button>
        </Notice>
      )}
      {query.data && (
        <>
          <label>
            Ссылка-приглашение
            <input
              ref={input}
              name="invite_link"
              autoComplete="off"
              spellCheck={false}
              value={query.data.url}
              readOnly
              onFocus={(event) => event.target.select()}
            />
          </label>
          <div className="invite-actions">
            <button className="secondary" onClick={copy}>
              {copied ? (
                <Check aria-hidden="true" size={18} />
              ) : (
                <Copy aria-hidden="true" size={18} />
              )}{" "}
              {copied ? "Скопировано" : "Скопировать"}
            </button>
            <button className="primary" onClick={share}>
              <Send aria-hidden="true" size={18} />
              Отправить
            </button>
          </div>
          <p className="caption">
            Ссылка действует до{" "}
            {new Intl.DateTimeFormat("ru", {
              day: "numeric",
              month: "long",
            }).format(new Date(query.data.expires_at))}
            .
          </p>
        </>
      )}
    </Sheet>
  );
}
export function IncomingInvite({
  token,
  close,
  completed,
}: {
  token: string;
  close(): void;
  completed(): void;
}) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["incoming-invite", token],
    queryFn: () =>
      api<InvitePreview>("/social/invites/" + encodeURIComponent(token)),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: () =>
      api<RequestResult>("/social/requests", {
        method: "POST",
        body: JSON.stringify({ invite_token: token }),
      }),
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["friends"] });
      haptic("success");
      completed();
    },
  });
  return (
    <Sheet
      title="Приглашение в друзья"
      close={close}
      canClose={!mutation.isPending}
    >
      {query.isPending && <p role="status">Проверяем приглашение…</p>}
      {query.error && <Notice>{errorText(query.error)}</Notice>}
      {query.data && (
        <>
          <div className="invite-person">
            <Avatar
              large
              name={query.data.user.display_name}
              url={query.data.user.photo_url}
            />
            <h3>{query.data.user.display_name}</h3>
          </div>
          {query.data.is_self ? (
            <p className="muted">
              Это ваша ссылка. Отправьте её человеку, которого хотите добавить.
            </p>
          ) : query.data.already_friends ? (
            <p className="muted">Вы уже друзья.</p>
          ) : query.data.pending_request_id ? (
            <>
              <p className="muted">Между вами уже есть заявка.</p>
              <button className="primary" onClick={completed}>
                Перейти к заявкам
              </button>
            </>
          ) : (
            <>
              <p className="muted">
                Друзья видят отмеченный статус и подтверждённые часы друг друга.
                Подробные отметки остаются личными.
              </p>
              <button
                className="primary"
                disabled={mutation.isPending || mutation.isSuccess}
                onClick={() => mutation.mutate()}
              >
                {mutation.isPending ? "Отправляем…" : "Отправить заявку"}
              </button>
            </>
          )}
        </>
      )}
      {mutation.error && <Notice>{errorText(mutation.error)}</Notice>}
    </Sheet>
  );
}
