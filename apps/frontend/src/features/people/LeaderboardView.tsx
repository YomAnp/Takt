import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Trophy } from "lucide-react";
import { api, errorText, type Profile } from "../../shared/api/client";
import { duration } from "../../shared/lib/time";
import { usePageVisible } from "../../shared/lib/visibility";
import { Avatar } from "../../shared/ui/Avatar";
import { Notice } from "../../shared/ui/Notice";
import {
  periodLabels,
  type LeaderboardPage,
  type Period,
  type RankingEntry,
  type Scope,
} from "./types";

export function LeaderboardView({
  profile,
  saved,
}: {
  profile: Profile;
  saved(profile: Profile): void;
}) {
  const visible = usePageVisible();
  const cache = useQueryClient();
  const [scope, setScope] = useState<Scope>("global");
  const [period, setPeriod] = useState<Period>("week");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["leaderboard", scope, period, offset],
    queryFn: () =>
      api<LeaderboardPage>(
        "/social/leaderboard?scope=" +
          scope +
          "&period=" +
          period +
          "&offset=" +
          offset,
      ),
    enabled: visible,
    refetchInterval: visible ? 30_000 : false,
    refetchIntervalInBackground: false,
  });
  const participation = useMutation({
    mutationFn: () =>
      api<Profile>("/me/preferences", {
        method: "PUT",
        body: JSON.stringify({
          display_name: profile.display_name,
          end_time: profile.end_time || "18:00",
          leaderboard_enabled: true,
        }),
      }),
    onSuccess: (value) => {
      saved(value);
      cache.invalidateQueries({ queryKey: ["leaderboard"] });
    },
  });
  const own = query.data?.current_user;
  return (
    <div className="leaderboard-content">
      <div className="ranking-controls">
        <div className="scope-control" aria-label="Круг участников">
          <button
            aria-pressed={scope === "global"}
            className={scope === "global" ? "selected" : ""}
            onClick={() => {
              setScope("global");
              setOffset(0);
            }}
          >
            Все
          </button>
          <button
            aria-pressed={scope === "friends"}
            className={scope === "friends" ? "selected" : ""}
            onClick={() => {
              setScope("friends");
              setOffset(0);
            }}
          >
            Друзья
          </button>
        </div>
        <select
          aria-label="Период рейтинга"
          value={period}
          onChange={(event) => {
            setPeriod(event.target.value as Period);
            setOffset(0);
          }}
        >
          {Object.entries(periodLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <p className="caption">
        Подтверждённые часы присутствия. Открытые интервалы в итог не входят.
      </p>
      {scope === "global" && !profile.leaderboard_enabled && (
        <div className="ranking-consent">
          <p>В общем рейтинге вы участвуете по желанию.</p>
          <button
            className="text-button"
            disabled={participation.isPending}
            onClick={() => participation.mutate()}
          >
            {participation.isPending ? "Сохраняем…" : "Включить участие"}
          </button>
        </div>
      )}
      {participation.error && <Notice>{errorText(participation.error)}</Notice>}
      {query.isPending && (
        <p className="loading-copy" role="status">
          Загружаем рейтинг…
        </p>
      )}
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
          {query.data.items.length ? (
            <>
              <div className="ranking-heading">
                <span>Место</span>
                <span>Участник</span>
                <span>Часы</span>
              </div>
              <ol className="ranking-list">
                {query.data.items.map((entry) => (
                  <RankingRow key={entry.user.id} entry={entry} />
                ))}
              </ol>
            </>
          ) : (
            <div className="people-empty">
              <Trophy aria-hidden="true" size={28} />
              <h2>Пока без итогов</h2>
              <p>
                {scope === "friends"
                  ? "Здесь появятся подтверждённые часы ваших друзей."
                  : "Рейтинг появится, когда участники подтвердят свои первые отметки."}
              </p>
            </div>
          )}
          {own && !query.data.items.some((entry) => entry.is_self) && (
            <div className="my-ranking">
              <span className="caption">Моё место</span>
              <ol className="ranking-list">
                <RankingRow entry={own} />
              </ol>
            </div>
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
        </>
      )}
    </div>
  );
}
function RankingRow({ entry }: { entry: RankingEntry }) {
  return (
    <li className={"ranking-row " + (entry.is_self ? "is-self" : "")}>
      <span className="rank-number">{entry.rank}</span>
      <Avatar name={entry.user.display_name} url={entry.user.photo_url} />
      <span className="person-copy">
        <strong>{entry.user.display_name}</strong>
        {entry.is_self && <small>Вы</small>}
      </span>
      <strong className="ranking-hours">{duration(entry.seconds)}</strong>
    </li>
  );
}
