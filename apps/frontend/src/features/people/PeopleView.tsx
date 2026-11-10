import { useState } from "react";
import type { Profile } from "../../shared/api/client";
import { FriendsView } from "./FriendsView";
import { LeaderboardView } from "./LeaderboardView";

export function PeopleView({
  profile,
  zone,
  saved,
}: {
  profile: Profile;
  zone: string;
  saved(profile: Profile): void;
}) {
  const [view, setView] = useState<"friends" | "ranking">("friends");
  return (
    <section className="people" aria-labelledby="people-title">
      <div className="screen-heading">
        <h1 id="people-title">Люди</h1>
      </div>
      <div
        className="people-tabs"
        role="tablist"
        aria-label="Люди"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          event.preventDefault();
          const next =
            event.key === "Home"
              ? "friends"
              : event.key === "End"
                ? "ranking"
                : view === "friends"
                  ? "ranking"
                  : "friends";
          setView(next);
          document
            .getElementById(next === "friends" ? "friends-tab" : "ranking-tab")
            ?.focus();
        }}
      >
        <button
          id="friends-tab"
          tabIndex={view === "friends" ? 0 : -1}
          role="tab"
          aria-selected={view === "friends"}
          aria-controls="friends-panel"
          onClick={() => setView("friends")}
        >
          Друзья
        </button>
        <button
          id="ranking-tab"
          tabIndex={view === "ranking" ? 0 : -1}
          role="tab"
          aria-selected={view === "ranking"}
          aria-controls="ranking-panel"
          onClick={() => setView("ranking")}
        >
          Рейтинг
        </button>
      </div>
      <div
        id={view === "friends" ? "friends-panel" : "ranking-panel"}
        role="tabpanel"
        aria-labelledby={view === "friends" ? "friends-tab" : "ranking-tab"}
      >
        {view === "friends" ? (
          <FriendsView zone={zone} />
        ) : (
          <LeaderboardView profile={profile} saved={saved} />
        )}
      </div>
    </section>
  );
}
