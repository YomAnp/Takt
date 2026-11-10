import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Check,
  ChevronRight,
  Cigarette,
  RefreshCw,
  UserRoundPlus,
  X,
} from "lucide-react";
import { api, errorText } from "../../shared/api/client";
import { clock, duration } from "../../shared/lib/time";
import { usePageVisible } from "../../shared/lib/visibility";
import { haptic } from "../../shared/lib/telegram";
import { Avatar } from "../../shared/ui/Avatar";
import { Notice } from "../../shared/ui/Notice";
import { Sheet } from "../../shared/ui/Sheet";
import { InviteShare } from "./InviteSheet";
import {
  periodLabels,
  type FriendProfile,
  type FriendRequest,
  type FriendsPage,
  type FriendSummary,
  type Period,
} from "./types";

function statusText(user: FriendSummary, zone: string) {
  const labels = {
    working: "На работе",
    on_break: "На перерыве",
    smoking: "На перекуре",
    away: "Без активной отметки",
    needs_checkout: "Уточняет прошлый день",
  };
  return (
    labels[user.status] +
    (user.status_since &&
    (user.status === "smoking" || user.status === "on_break")
      ? " с " + clock(user.status_since, zone)
      : "")
  );
}
export function FriendsView({ zone }: { zone: string }) {
  const visible = usePageVisible();
  const cache = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [inviting, setInviting] = useState(false);
  const [selected, setSelected] = useState<FriendSummary | null>(null);
  const query = useQuery({
    queryKey: ["friends", offset],
    queryFn: () => api<FriendsPage>("/social/friends?offset=" + offset),
    enabled: visible,
    refetchInterval: visible ? 30_000 : false,
    refetchIntervalInBackground: false,
  });
  const mutation = useMutation({
    mutationFn: ({
      request,
      action,
    }: {
      request: FriendRequest;
      action: "accept" | "decline" | "cancel";
    }) =>
      api("/social/requests/" + request.id + "/" + action, { method: "POST" }),
    onSuccess: () => haptic("success"),
    onSettled: () => {
      cache.invalidateQueries({ queryKey: ["friends"] });
      cache.invalidateQueries({ queryKey: ["leaderboard"] });
    },
  });
  return (
    <div className="friends-content">
      <div className="people-toolbar">
        <p className="muted">
          {query.data?.total
            ? query.data.total + " " + friendWord(query.data.total)
            : "Статусы и время тех, с кем вы работаете"}
        </p>
        <button
          className="round-action"
          aria-label="Пригласить друга"
          onClick={() => setInviting(true)}
        >
          <UserRoundPlus aria-hidden="true" size={20} />
        </button>
      </div>
      {query.isPending && (
        <p className="loading-copy" role="status">
          Загружаем друзей…
        </p>
      )}
      {query.error && (
        <Notice>
          {errorText(query.error)}{" "}
          <button className="text-button" onClick={() => query.refetch()}>
            <RefreshCw aria-hidden="true" size={16} />
            Повторить
          </button>
        </Notice>
      )}
      {query.data && (
        <>
          {query.data.incoming.length > 0 && (
            <section className="requests-section">
              <h2>
                Заявки <span>{query.data.incoming.length}</span>
              </h2>
              <p className="caption">
                После принятия друг увидит ваш отмеченный статус и
                подтверждённые часы.
              </p>
              <RequestRows
                requests={query.data.incoming}
                busy={mutation.isPending}
                act={(request, action) => mutation.mutate({ request, action })}
              />
            </section>
          )}
          {!query.data.items.length && offset === 0 ? (
            <div className="people-empty">
              <UserRoundPlus aria-hidden="true" size={28} />
              <h2>Добавьте своих</h2>
              <p>
                Пригласите коллегу по ссылке. После подтверждения здесь появится
                его статус.
              </p>
              <button className="secondary" onClick={() => setInviting(true)}>
                Пригласить друга
              </button>
            </div>
          ) : (
            <section className="friends-section" aria-label="Список друзей">
              <div className="list-heading">
                <h2>Друзья</h2>
                <span>Часы за неделю</span>
              </div>
              {query.data.items.map((user) => (
                <button
                  key={user.id}
                  className="person-row"
                  onClick={() => setSelected(user)}
                >
                  <Avatar name={user.display_name} url={user.photo_url} />
                  <span className="person-copy">
                    <strong>{user.display_name}</strong>
                    <small className={"friend-status " + user.status}>
                      {user.status === "smoking" ? (
                        <Cigarette aria-hidden="true" size={14} />
                      ) : (
                        <i className="status-dot" />
                      )}
                      {statusText(user, zone)}
                    </small>
                  </span>
                  <span className="person-hours">
                    {duration(user.confirmed_seconds)}
                  </span>
                  <ChevronRight aria-hidden="true" size={16} />
                </button>
              ))}
            </section>
          )}
          {(query.data.total > 30 || offset > 0) && (
            <div className="pagination">
              <button
                className="text-button"
                disabled={offset === 0 || query.isFetching}
                onClick={() => setOffset(Math.max(0, offset - 30))}
              >
                Назад
              </button>
              <span className="caption">
                {offset + 1}–
                {Math.min(offset + query.data.items.length, query.data.total)}{" "}
                из {query.data.total}
              </span>
              <button
                className="text-button"
                disabled={offset + 30 >= query.data.total || query.isFetching}
                onClick={() => setOffset(offset + 30)}
              >
                Далее
              </button>
            </div>
          )}
          {query.data.outgoing.length > 0 && (
            <details className="outgoing-requests">
              <summary>
                Отправленные заявки <span>{query.data.outgoing.length}</span>
              </summary>
              <RequestRows
                requests={query.data.outgoing}
                busy={mutation.isPending}
                act={(request, action) => mutation.mutate({ request, action })}
              />
            </details>
          )}
          <p className="caption status-explanation">
            Статусы отражают отметки в Такте, а не присутствие в Telegram.
            Обновлено {clock(query.data.as_of, zone)}.
          </p>
        </>
      )}
      {mutation.error && <Notice>{errorText(mutation.error)}</Notice>}
      {inviting && <InviteShare close={() => setInviting(false)} />}
      {selected && (
        <FriendDetails
          friend={selected}
          zone={zone}
          close={() => setSelected(null)}
        />
      )}
    </div>
  );
}
function friendWord(value: number) {
  const n = value % 100;
  return n >= 11 && n <= 14
    ? "друзей"
    : value % 10 === 1
      ? "друг"
      : value % 10 >= 2 && value % 10 <= 4
        ? "друга"
        : "друзей";
}
function RequestRows({
  requests,
  busy,
  act,
}: {
  requests: FriendRequest[];
  busy: boolean;
  act(request: FriendRequest, action: "accept" | "decline" | "cancel"): void;
}) {
  return (
    <div className="request-list">
      {requests.map((request) => (
        <div className="person-row request-row" key={request.id}>
          <Avatar
            name={request.user.display_name}
            url={request.user.photo_url}
          />
          <span className="person-copy">
            <strong>{request.user.display_name}</strong>
            <small>
              {request.direction === "incoming"
                ? "Хочет добавить вас"
                : "Ждём подтверждения"}
            </small>
          </span>
          <div className="request-actions">
            {request.direction === "incoming" ? (
              <>
                <button
                  className="accept-request"
                  disabled={busy}
                  onClick={() => act(request, "accept")}
                  aria-label={"Принять заявку от " + request.user.display_name}
                >
                  <Check aria-hidden="true" size={18} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => act(request, "decline")}
                  aria-label={
                    "Отклонить заявку от " + request.user.display_name
                  }
                >
                  <X aria-hidden="true" size={18} />
                </button>
              </>
            ) : (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => act(request, "cancel")}
                aria-label={"Отменить заявку для " + request.user.display_name}
              >
                Отменить
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
function FriendDetails({
  friend,
  zone,
  close,
}: {
  friend: FriendSummary;
  zone: string;
  close(): void;
}) {
  const visible = usePageVisible();
  const cache = useQueryClient();
  const [period, setPeriod] = useState<Period>("week");
  const query = useQuery({
    queryKey: ["friend", friend.id, period],
    queryFn: () =>
      api<FriendProfile>("/social/friends/" + friend.id + "?period=" + period),
    enabled: visible,
    refetchInterval: visible ? 30_000 : false,
  });
  const remove = useMutation({
    mutationFn: (friendshipId: string | null) =>
      api(
        "/social/friends/" +
          friend.id +
          (friendshipId
            ? "?friendship_id=" + encodeURIComponent(friendshipId)
            : ""),
        { method: "DELETE" },
      ),
    onSuccess: () => close(),
    onSettled: () => {
      cache.invalidateQueries({ queryKey: ["friends"] });
      cache.invalidateQueries({ queryKey: ["leaderboard"] });
      cache.invalidateQueries({ queryKey: ["friend", friend.id] });
    },
  });
  return (
    <Sheet title="Друг" close={close} canClose={!remove.isPending}>
      <div className="friend-profile">
        <Avatar large name={friend.display_name} url={friend.photo_url} />
        <h3>{friend.display_name}</h3>
        <p className="friend-status">
          {statusText(query.data || friend, zone)}
        </p>
      </div>
      <label className="period-label">
        Подтверждённые часы
        <select
          value={period}
          onChange={(event) => setPeriod(event.target.value as Period)}
        >
          {Object.entries(periodLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {query.isPending ? (
        <p className="loading-copy" role="status">
          Загружаем время…
        </p>
      ) : query.error ? (
        <Notice>{errorText(query.error)}</Notice>
      ) : (
        <p className="friend-time">
          {duration(query.data?.confirmed_seconds)}
          <span>часов присутствия</span>
        </p>
      )}
      <button
        className="text-button danger-action"
        disabled={remove.isPending || query.isPending || !!query.error}
        onClick={() => {
          if (
            window.confirm(
              "Удалить из друзей? Ваши статусы и часы больше не будут доступны друг другу.",
            )
          )
            remove.mutate(
              query.data?.friendship_id ?? friend.friendship_id ?? null,
            );
        }}
      >
        {remove.isPending ? "Удаляем…" : "Удалить из друзей"}
      </button>
      {remove.error && <Notice>{errorText(remove.error)}</Notice>}
    </Sheet>
  );
}
