import { DayView } from "../features/day/DayView";
import { TimeDialog } from "../features/day/TimeDialog";
import { useTimeAccounting } from "../features/day/useTimeAccounting";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  ChartNoAxesColumnIncreasing,
  Check,
  ChevronRight,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { errorText, login, type Profile } from "../shared/api/client";
import { Admin } from "../features/admin/AdminView";
import { PreferencesForm } from "../features/profile/PreferencesForm";
import { Statistics } from "../features/statistics/Statistics";
import { Flower } from "../shared/ui/Flower";
import { applyTelegramTheme, telegram } from "../shared/lib/telegram";

let opening: Promise<Profile> | null = null;
export function App() {
  const cache = useQueryClient();
  const [view, setView] = useState("day");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [bootError, setBootError] = useState<unknown>(null);
  const [outside, setOutside] = useState(false);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    const webapp = telegram();
    if (!webapp?.initData) {
      setOutside(true);
      return;
    }
    if (!opening) opening = login(webapp.initData);
    opening.then(setProfile).catch(setBootError);
    const refresh = () => cache.invalidateQueries({ queryKey: ["state"] });
    const theme = () => applyTelegramTheme(webapp);
    webapp.onEvent?.("activated", refresh);
    webapp.onEvent?.("themeChanged", theme);
    return () => {
      webapp.offEvent?.("activated", refresh);
      webapp.offEvent?.("themeChanged", theme);
    };
  }, [cache]);
  const account = useTimeAccounting(profile, setAnnouncement);
  const saved = (value: Profile) => {
    setProfile(value);
    cache.invalidateQueries({ queryKey: ["state"] });
    setAnnouncement("Настройки сохранены");
  };

  return (
    <div className="workspace">
      <aside className="desktop-note">
        <Flower />
        <span>Такт</span>
        <h2>
          Рабочий день.
          <br />В своём ритме.
        </h2>
        <p>
          Отметки, время и немного порядка
          <br />в повседневных делах.
        </p>
        <small>МГРИ</small>
      </aside>
      <div className="app-shell">
        <header className="app-header">
          <a
            className="wordmark"
            href="/"
            aria-label="Такт, главный экран"
            onClick={(event) => {
              event.preventDefault();
              setView("day");
            }}
          >
            <Flower small />
            <span>такт</span>
          </a>
          <button
            className="profile-button"
            onClick={() => setView("settings")}
            aria-label="Мои настройки"
          >
            {profile?.display_name.slice(0, 1) || <Settings2 size={20} />}
            <i />
          </button>
        </header>
        <main>
          {outside || bootError ? (
            <section className="welcome">
              <Flower />
              <h1>
                {outside ? "Ваш день начинается здесь" : "Не удалось войти"}
              </h1>
              <p className="muted">
                {outside
                  ? "Откройте Такт через кнопку приложения в Telegram-боте, чтобы войти и отметить приход."
                  : errorText(bootError)}
              </p>
              <div className="welcome-sample">
                <span>Рабочий день</span>
                <strong>В своём ритме</strong>
                <p>
                  Время сохраняется по вашим отметкам. Перерывы можно отмечать
                  для себя.
                </p>
              </div>
            </section>
          ) : !profile ? (
            <section className="loading" role="status">
              <Flower />
              <p>Открываем ваш день…</p>
            </section>
          ) : !profile.onboarded ? (
            <section className="welcome">
              <p className="greeting">Рады знакомству</p>
              <h1>
                Привет.
                <br />
                Это Такт.
              </h1>
              <p className="muted">
                Отмечайте приход и уход — остальное посчитаем. Для начала пара
                настроек.
              </p>
              <PreferencesForm profile={profile} welcome saved={saved} />
            </section>
          ) : view === "stats" ? (
            <Statistics />
          ) : view === "admin" ? (
            <Admin profile={profile} back={() => setView("settings")} />
          ) : view === "settings" ? (
            <section className="settings">
              <h1>Настройки</h1>
              <p className="muted">Ваш рабочий день</p>
              <PreferencesForm profile={profile} saved={saved} />
              <div className="settings-links">
                {profile.role !== "member" && (
                  <button onClick={() => setView("admin")}>
                    <ShieldCheck size={20} />
                    <span>Пользователи</span>
                    <ChevronRight size={18} />
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
          {announcement && (
            <p className="announcement" role="status">
              <Check size={16} />
              {announcement}
            </p>
          )}
        </main>
        {profile?.onboarded && (
          <nav className="bottom-nav" aria-label="Разделы">
            {[
              ["day", CalendarDays, "Мой день"],
              ["stats", ChartNoAxesColumnIncreasing, "Статистика"],
              ["settings", Settings2, "Настройки"],
            ].map(([key, Icon, label]) => {
              const NavIcon = Icon as typeof CalendarDays;
              return (
                <button
                  key={key as string}
                  className={
                    view === key || (view === "admin" && key === "settings")
                      ? "selected"
                      : ""
                  }
                  aria-current={view === key ? "page" : undefined}
                  onClick={() => setView(key as string)}
                >
                  <NavIcon size={21} />
                  <span>{label as string}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>
      <TimeDialog account={account} />
    </div>
  );
}
