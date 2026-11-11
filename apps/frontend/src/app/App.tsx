import { lazy, Suspense, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  Settings2,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { errorText, login, ApiError, type Profile } from "../shared/api/client";
import { PreferencesForm } from "../features/profile/PreferencesForm";
import { DayView } from "../features/day/DayView";
import { TimeDialog } from "../features/day/TimeDialog";
import { useTimeAccounting } from "../features/day/useTimeAccounting";
import { IncomingInvite } from "../features/people/InviteSheet";
import { BrandMark } from "../shared/ui/BrandMark";
import {
  applyTelegramTheme,
  clearIncomingInvite,
  haptic,
  incomingInvite,
  observeTelegram,
  telegram,
  useTelegramBack,
} from "../shared/lib/telegram";

const Statistics = lazy(() =>
  import("../features/statistics/Statistics").then((module) => ({
    default: module.Statistics,
  })),
);
const Admin = lazy(() =>
  import("../features/admin/AdminView").then((module) => ({
    default: module.Admin,
  })),
);
const PeopleView = lazy(() =>
  import("../features/people/PeopleView").then((module) => ({
    default: module.PeopleView,
  })),
);
type View = "day" | "people" | "stats" | "settings" | "admin";
let opening: Promise<Profile> | null = null;

export function App() {
  const cache = useQueryClient();
  const [view, setView] = useState<View>("day");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [bootError, setBootError] = useState<unknown>(null);
  const [outside, setOutside] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [invite, setInvite] = useState(incomingInvite);
  useEffect(() => {
    const app = telegram();
    const stopObserving = observeTelegram(app);
    if (!app?.initData) {
      setOutside(true);
      return stopObserving;
    }
    if (!opening) opening = login(app.initData);
    let active = true;
    opening
      .then((value) => {
        if (active) setProfile(value);
      })
      .catch((error) => {
        if (active) setBootError(error);
      });
    const refresh = () => {
      cache.invalidateQueries({ queryKey: ["state"] });
      cache.invalidateQueries({ queryKey: ["friends"] });
      cache.invalidateQueries({ queryKey: ["leaderboard"] });
    };
    const theme = () => applyTelegramTheme(app);
    app.onEvent?.("activated", refresh);
    app.onEvent?.("themeChanged", theme);
    return () => {
      active = false;
      stopObserving();
      app.offEvent?.("activated", refresh);
      app.offEvent?.("themeChanged", theme);
    };
  }, [cache, attempt]);
  const account = useTimeAccounting(profile, setAnnouncement);
  useTelegramBack(
    profile?.onboarded && view !== "day"
      ? () => setView(view === "admin" ? "settings" : "day")
      : null,
  );
  function saved(value: Profile) {
    setProfile(value);
    cache.invalidateQueries({ queryKey: ["state"] });
    cache.invalidateQueries({ queryKey: ["leaderboard"] });
    setAnnouncement("Настройки сохранены");
  }
  function closeInvite() {
    setInvite(null);
    clearIncomingInvite();
  }
  const navigation = [
    { key: "day", icon: CalendarDays, label: "Мой день" },
    { key: "people", icon: UsersRound, label: "Люди" },
    { key: "stats", icon: ChartNoAxesColumnIncreasing, label: "Статистика" },
    { key: "settings", icon: Settings2, label: "Настройки" },
  ] as const;
  return (
    <div className="workspace">
      <div className="app-shell">
        <a className="skip-link" href="#main-content">
          К содержимому
        </a>
        <main id="main-content" tabIndex={-1}>
          <Suspense
            fallback={
              <p className="loading-copy" role="status">
                Открываем раздел…
              </p>
            }
          >
            {outside || bootError ? (
              <section className="welcome">
                <BrandMark />
                <h1>{outside ? "Такт в Telegram" : "Не удалось войти"}</h1>
                <p className="muted">
                  {outside
                    ? "Откройте приложение через кнопку «Открыть Такт» в Telegram-боте."
                    : errorText(bootError)}
                </p>
                {bootError instanceof ApiError && bootError.status === 0 && (
                  <button
                    className="secondary"
                    onClick={() => {
                      opening = null;
                      setBootError(null);
                      setAttempt((value) => value + 1);
                    }}
                  >
                    Повторить вход
                  </button>
                )}
              </section>
            ) : !profile ? (
              <section className="loading" role="status">
                <BrandMark />
                <p>Открываем ваш день…</p>
              </section>
            ) : !profile.onboarded ? (
              <section className="welcome">
                <BrandMark />
                <h1>
                  Привет.
                  <br />
                  Это Такт.
                </h1>
                <p className="muted">
                  Отмечайте приход и уход. Для начала настройте свой день.
                </p>
                <PreferencesForm profile={profile} welcome saved={saved} />
              </section>
            ) : view === "stats" ? (
              <Statistics />
            ) : view === "people" ? (
              <PeopleView profile={profile} zone={account.zone} saved={saved} />
            ) : view === "admin" ? (
              <Admin profile={profile} back={() => setView("settings")} />
            ) : view === "settings" ? (
              <section className="settings">
                <div className="screen-heading">
                  <h1>Настройки</h1>
                </div>
                <PreferencesForm profile={profile} saved={saved} />
                <div className="settings-links">
                  {profile.role !== "member" && (
                    <button onClick={() => setView("admin")}>
                      <ShieldCheck aria-hidden="true" size={20} />
                      <span>Пользователи</span>
                      <ChevronRight aria-hidden="true" size={18} />
                    </button>
                  )}
                  <div>
                    <span className="caption">Вход через Telegram</span>
                    <strong>
                      {profile.telegram_username
                        ? "@" + profile.telegram_username
                        : profile.telegram_id}
                    </strong>
                  </div>
                </div>
              </section>
            ) : (
              <DayView profile={profile} account={account} />
            )}
          </Suspense>
          <p className="sr-only" role="status">
            {announcement}
          </p>
        </main>
        {profile?.onboarded && (
          <nav className="bottom-nav" aria-label="Разделы">
            {navigation.map(({ key, icon: Icon, label }) => {
              const selected =
                view === key || (view === "admin" && key === "settings");
              return (
                <button
                  key={key}
                  className={selected ? "selected" : ""}
                  aria-current={selected ? "page" : undefined}
                  onClick={() => {
                    haptic();
                    setView(key);
                  }}
                >
                  <Icon aria-hidden="true" size={21} />
                  <span>{label}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>
      <TimeDialog account={account} />
      {profile?.onboarded && invite && (
        <IncomingInvite
          token={invite}
          close={closeInvite}
          completed={() => {
            closeInvite();
            setView("people");
            setAnnouncement("Заявки обновлены");
          }}
        />
      )}
    </div>
  );
}
