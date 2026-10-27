import { useEffect, useState } from "react";
import { ArrowLeft, ShieldCheck, UserRound, Search } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  errorText,
  type AccessChange,
  type Profile,
  type Summary,
} from "../../shared/api/client";
import { duration } from "../../shared/lib/time";
import { Notice } from "../../shared/ui/Notice";
import { Sheet } from "../../shared/ui/Sheet";
export function Admin({ profile, back }: { profile: Profile; back(): void }) {
  const cache = useQueryClient();
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [day, setDay] = useState(new Date().toLocaleDateString("en-CA"));
  useEffect(() => {
    const timeout = setTimeout(() => {
      setSearch(text);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timeout);
  }, [text]);
  const query = useQuery({
    queryKey: ["users", search, offset],
    queryFn: () =>
      api<Profile[]>(
        "/admin/users?q=" + encodeURIComponent(search) + "&offset=" + offset,
      ),
  });
  const summary = useQuery({
    queryKey: ["employee", selected?.id, day],
    queryFn: () =>
      api<Summary | null>(
        "/admin/users/" + selected!.id + "/day?work_date=" + day,
      ),
    enabled: !!selected && !!day,
  });
  const mutation = useMutation({
    mutationFn: ({ user, change }: { user: Profile; change: AccessChange }) =>
      api<Profile>("/admin/users/" + user.id, {
        method: "PATCH",
        body: JSON.stringify(change),
      }),
    onSuccess: (user) => {
      setSelected(user);
      cache.invalidateQueries({ queryKey: ["users"] });
    },
  });
  return (
    <section className="admin">
      <button className="text-button back" onClick={back}>
        <ArrowLeft size={18} />
        Настройки
      </button>
      <h1>Пользователи</h1>
      <p className="muted">Доступ и индивидуальный учёт</p>
      <label className="search">
        <Search size={19} />
        <input
          aria-label="Поиск пользователей"
          value={text}
          placeholder="Имя или @username"
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      {query.isPending && <p role="status">Загружаем пользователей…</p>}
      {query.error && <Notice>{errorText(query.error)}</Notice>}
      <div className="user-list">
        {query.data?.map((user) => (
          <button
            className="user-row"
            key={user.id}
            onClick={() => {
              setSelected(user);
              mutation.reset();
            }}
          >
            <span className="avatar">
              {user.display_name.slice(0, 1) || <UserRound size={18} />}
            </span>
            <span>
              <strong>{user.display_name || "Без имени"}</strong>
              <small>
                {user.telegram_username
                  ? "@" + user.telegram_username
                  : user.telegram_id}{" "}
                ·{" "}
                {user.role === "superadmin"
                  ? "Владелец"
                  : user.role === "admin"
                    ? "Администратор"
                    : user.is_active
                      ? "Участник"
                      : "Доступ приостановлен"}
              </small>
            </span>
            {user.role !== "member" && <ShieldCheck size={19} />}
          </button>
        ))}
      </div>
      {query.data?.length === 0 && (
        <p className="empty-copy">Пользователи не найдены.</p>
      )}
      <div className="pagination">
        <button
          className="text-button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 30))}
        >
          Назад
        </button>
        <button
          className="text-button"
          disabled={(query.data?.length || 0) < 30}
          onClick={() => setOffset(offset + 30)}
        >
          Далее
        </button>
      </div>
      {selected && (
        <Sheet
          title={selected.display_name || "Участник"}
          close={() => setSelected(null)}
        >
          <p className="muted">
            {selected.telegram_username
              ? "@" + selected.telegram_username
              : "Telegram ID: " + selected.telegram_id}
          </p>
          <label>
            День учёта
            <input
              type="date"
              value={day}
              onChange={(event) => setDay(event.target.value)}
            />
          </label>
          {summary.isPending ? (
            <p role="status">Загружаем учёт…</p>
          ) : summary.error ? (
            <Notice>{errorText(summary.error)}</Notice>
          ) : (
            <div className="detail-stats">
              <div>
                <strong>{duration(summary.data?.total_seconds)}</strong>
                <span>присутствие</span>
              </div>
              <div>
                <strong>{duration(summary.data?.break_seconds)}</strong>
                <span>перерывы</span>
              </div>
              <div>
                <strong>{duration(summary.data?.overtime_seconds)}</strong>
                <span>после окончания</span>
              </div>
            </div>
          )}
          {summary.data?.state === "needs_checkout" && (
            <p className="muted">
              Сотрудник уточняет время ухода. Итог ещё не подтверждён.
            </p>
          )}
          {!summary.data && !summary.isPending && (
            <p className="muted">На эту дату учёт не настроен.</p>
          )}
          {selected.id !== profile.id && selected.role !== "superadmin" && (
            <div className="admin-actions">
              {(profile.role === "superadmin" ||
                selected.role === "member") && (
                <button
                  className="secondary"
                  disabled={mutation.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        selected.is_active
                          ? "Приостановить доступ этого пользователя?"
                          : "Восстановить доступ?",
                      )
                    )
                      mutation.mutate({
                        user: selected,
                        change: { is_active: !selected.is_active },
                      });
                  }}
                >
                  {selected.is_active
                    ? "Приостановить доступ"
                    : "Восстановить доступ"}
                </button>
              )}
              {profile.role === "superadmin" && (
                <button
                  className="secondary"
                  disabled={mutation.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        selected.role === "admin"
                          ? "Снять права администратора?"
                          : "Назначить администратором? Он сможет видеть учёт сотрудников и управлять доступом участников.",
                      )
                    )
                      mutation.mutate({
                        user: selected,
                        change: {
                          role: selected.role === "admin" ? "member" : "admin",
                        },
                      });
                  }}
                >
                  {selected.role === "admin"
                    ? "Снять права администратора"
                    : "Назначить администратором"}
                </button>
              )}
            </div>
          )}
          {mutation.error && <Notice>{errorText(mutation.error)}</Notice>}
        </Sheet>
      )}
    </section>
  );
}
