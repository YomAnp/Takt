import { expect, test, type Page } from "@playwright/test";

const SELF = "11111111-1111-4111-8111-111111111111";
const FRIEND = "22222222-2222-4222-8222-222222222222";
const EDGE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const INVITE = "abcdefghijklmnopqrstuvxyz123456789";
const NOW = "2026-11-10T10:00:00Z";
const baseProfile = {
  id: SELF,
  display_name: "Анна Семёнова",
  telegram_id: 123,
  telegram_username: "anna",
  role: "member",
  is_active: true,
  onboarded: true,
  end_time: "18:00:00",
  photo_url: null,
  leaderboard_enabled: false,
};
const baseSummary = {
  work_date: "2026-11-10",
  time_zone: "Europe/Moscow",
  as_of: NOW,
  state: "working",
  scheduled_end_at: "2026-11-10T15:00:00Z",
  seconds_until_end: 18000,
  total_seconds: 3600,
  break_seconds: 0,
  overtime_seconds: 0,
  confirmed_seconds: 0,
  is_provisional: true,
};
const peer = { id: FRIEND, display_name: "Дмитрий Михайлов", photo_url: null };

async function socialFixture(
  page: Page,
  options: {
    working?: boolean;
    longName?: boolean;
    onboarding?: boolean;
    empty?: boolean;
    expired?: boolean;
    insets?: boolean;
    renewDuringDelete?: boolean;
    dark?: boolean;
  } = {},
) {
  let user = { ...baseProfile, onboarded: !options.onboarding };
  let record: any = options.working
    ? {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        revision: 1,
        started_at: "2026-11-10T09:00:00Z",
        ended_at: null,
        breaks: [],
      }
    : null;
  let friends = options.empty
    ? []
    : [
        {
          ...peer,
          display_name: options.longName
            ? "Александра-Екатерина Константинопольская-Михайлова с очень длинным именем"
            : peer.display_name,
          status: "smoking",
          status_since: "2026-11-10T09:45:00Z",
          confirmed_seconds: 7200,
          friendship_id: EDGE,
        },
      ];
  let incoming = options.empty
    ? []
    : [
        {
          id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          user: {
            id: "33333333-3333-4333-8333-333333333333",
            display_name: "Мария Волкова",
            photo_url: null,
          },
          direction: "incoming",
          created_at: NOW,
        },
      ];
  let outgoing: any[] = [];
  const actions: Array<{ path: string; body: any; search: string }> = [];
  const counts = { friends: 0, ranking: 0 };
  let failedDelete = false;
  await page.route("https://telegram.org/js/**", (route) =>
    route.fulfill({ body: "" }),
  );
  await page.addInitScript(
    ({ dark, insets }) => {
      const handlers: Record<string, Array<() => void>> = {};
      let back: (() => void) | null = null;
      const app: any = {
        initData: "signed-test-fixture",
        colorScheme: dark ? "dark" : "light",
        viewportHeight: window.innerHeight,
        viewportStableHeight: window.innerHeight,
        safeAreaInset: {
          top: insets ? 20 : 0,
          bottom: insets ? 14 : 0,
          left: 0,
          right: 0,
        },
        contentSafeAreaInset: {
          top: insets ? 10 : 0,
          bottom: insets ? 8 : 0,
          left: 0,
          right: 0,
        },
        ready() {},
        expand() {},
        setHeaderColor() {},
        setBackgroundColor() {},
        setBottomBarColor() {},
        onEvent(name: string, fn: () => void) {
          (handlers[name] ||= []).push(fn);
        },
        offEvent(name: string, fn: () => void) {
          handlers[name] = (handlers[name] || []).filter((item) => item !== fn);
        },
        BackButton: {
          isVisible: false,
          show() {
            this.isVisible = true;
          },
          hide() {
            this.isVisible = false;
          },
          onClick(fn: () => void) {
            back = fn;
          },
          offClick(fn: () => void) {
            if (back === fn) back = null;
          },
        },
        HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
      };
      (window as any).Telegram = { WebApp: app };
      (window as any).__taktTest = {
        app,
        emit(name: string) {
          handlers[name]?.forEach((fn) => fn());
        },
        back() {
          back?.();
        },
      };
    },
    { dark: !!options.dark, insets: !!options.insets },
  );
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    const json = (body: any, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    const empty = () => route.fulfill({ status: 204, body: "" });
    if (path.endsWith("/auth/telegram"))
      return json({ token: "fixture-session", profile: user });
    if (path.endsWith("/me/preferences")) {
      user = { ...user, ...route.request().postDataJSON(), onboarded: true };
      return json(user);
    }
    if (path.endsWith("/me/state"))
      return json({
        now: NOW,
        time_zone: "Europe/Moscow",
        attendance: record,
        last_finished: null,
        pending: null,
        summary: {
          ...baseSummary,
          state: record
            ? record.breaks.some((item: any) => !item.ended_at)
              ? "on_break"
              : "working"
            : "not_started",
          total_seconds: record ? 3600 : 0,
          break_seconds: record?.breaks.some((item: any) => !item.ended_at)
            ? 180
            : 0,
          is_provisional: !!record,
        },
      });
    if (path.includes("/me/attendance/")) {
      const body = route.request().postDataJSON();
      actions.push({ path, body, search: url.search });
      if (path.endsWith("/start_break"))
        record = {
          ...record,
          revision: record.revision + 1,
          breaks: [
            ...record.breaks,
            {
              id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
              started_at: "2026-11-10T09:57:00Z",
              ended_at: null,
              kind: body.break_kind || "regular",
            },
          ],
        };
      if (path.endsWith("/end_break"))
        record = {
          ...record,
          revision: record.revision + 1,
          breaks: record.breaks.map((item: any) => ({
            ...item,
            ended_at: NOW,
          })),
        };
      return json({
        request_id: body.request_id,
        attendance: record,
        closed_break_id: null,
      });
    }
    if (path === "/api/v1/social/friends") {
      counts.friends++;
      return json({
        items: friends,
        total: friends.length,
        incoming,
        outgoing,
        as_of: NOW,
      });
    }
    if (path.startsWith("/api/v1/social/friends/")) {
      if (route.request().method() === "DELETE") {
        actions.push({ path, body: null, search: url.search });
        if (options.renewDuringDelete && !failedDelete) {
          failedDelete = true;
          friends = friends.map((item) => ({
            ...item,
            friendship_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
          }));
          return route.abort("failed");
        }
        if (
          options.renewDuringDelete &&
          url.searchParams.get("friendship_id") === EDGE
        )
          return json({ detail: { code: "friendship_changed" } }, 409);
        friends = friends.filter((item) => item.id !== path.split("/").pop());
        return empty();
      }
      const found = friends.find((item) => item.id === path.split("/").pop());
      return found
        ? json({
            ...found,
            period_start: "2026-11-09",
            period_end: "2026-11-10",
          })
        : json({ detail: { code: "friend_not_found" } }, 404);
    }
    if (path === "/api/v1/social/invite")
      return json({
        token: INVITE,
        url: "https://t.me/takt_test_bot?start=friend_" + INVITE,
        expires_at: "2026-11-17T10:00:00Z",
      });
    if (path.startsWith("/api/v1/social/invites/"))
      return options.expired
        ? json({ detail: { code: "invite_expired" } }, 404)
        : json({
            user: {
              id: "44444444-4444-4444-8444-444444444444",
              display_name: "Никита Сергеев",
              photo_url: null,
            },
            expires_at: "2026-11-17T10:00:00Z",
            is_self: false,
            already_friends: false,
            pending_request_id: null,
          });
    if (path === "/api/v1/social/requests") {
      const body = route.request().postDataJSON();
      actions.push({ path, body, search: url.search });
      const request = {
        id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
        user: {
          id: "44444444-4444-4444-8444-444444444444",
          display_name: "Никита Сергеев",
          photo_url: null,
        },
        created_at: NOW,
        direction: "outgoing",
      };
      outgoing = [request];
      return json({ request, status: "outgoing" });
    }
    if (path.startsWith("/api/v1/social/requests/")) {
      actions.push({ path, body: null, search: url.search });
      const id = path.split("/")[5],
        action = path.split("/").pop();
      const request = incoming.find((item) => item.id === id);
      if (action === "accept" && request)
        friends.push({
          ...request.user,
          status: "away",
          status_since: null as any,
          confirmed_seconds: 0,
          friendship_id: "ffffffff-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        });
      incoming = incoming.filter((item) => item.id !== id);
      outgoing = outgoing.filter((item) => item.id !== id);
      return empty();
    }
    if (path === "/api/v1/social/leaderboard") {
      counts.ranking++;
      const scope = url.searchParams.get("scope") || "global",
        period = url.searchParams.get("period") || "week";
      actions.push({ path, body: null, search: url.search });
      const own = {
        rank: 42,
        user: { id: SELF, display_name: user.display_name, photo_url: null },
        seconds: 1000,
        is_self: true,
      };
      const items = options.empty
        ? []
        : Array.from({ length: 30 }, (_, index) => ({
            rank: index + 1,
            user:
              index === 0
                ? peer
                : {
                    id:
                      "55555555-5555-4555-8555-" +
                      String(index).padStart(12, "0"),
                    display_name: "Участник " + (index + 1),
                    photo_url: null,
                  },
            seconds: 7200 - index * 100,
            is_self: false,
          }));
      return json({
        items,
        total: options.empty ? 0 : 42,
        current_user: options.empty
          ? null
          : scope === "friends" || user.leaderboard_enabled
            ? own
            : null,
        scope,
        period,
        period_start: period === "all" ? null : "2026-11-09",
        period_end: "2026-11-10",
        participating: scope === "friends" || user.leaderboard_enabled,
        as_of: NOW,
      });
    }
    if (path.endsWith("/me/history")) return json([]);
    return json({ detail: { code: "not_found" } }, 404);
  });
  return { actions, counts };
}

for (const [width, height] of [
  [320, 568],
  [360, 740],
  [375, 667],
  [390, 844],
  [430, 932],
  [768, 1024],
  [1280, 800],
]) {
  test(
    "day actions and navigation fit " + width + "x" + height,
    async ({ page }, info) => {
      await page.setViewportSize({ width, height });
      await socialFixture(page, { working: true });
      await page.goto("/");
      const finish = page.getByRole("button", {
        name: "Завершить день",
        exact: true,
      });
      const smoke = page.getByRole("button", {
        name: "На перекур",
        exact: true,
      });
      await expect(finish).toBeVisible();
      await expect(smoke).toBeVisible();
      const bounds = await smoke.boundingBox(),
        nav = await page
          .getByRole("navigation", { name: "Разделы" })
          .boundingBox();
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(nav!.y - 4);
      expect(nav!.y + nav!.height).toBeLessThanOrEqual(height + 1);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("day-" + width + ".png"),
        fullPage: false,
      });
    },
  );
}
test("smoke is an optional break and survives reopening", async ({ page }) => {
  const fixture = await socialFixture(page, { working: true });
  await page.goto("/");
  await page.getByRole("button", { name: "На перекур", exact: true }).click();
  await expect(page.getByText("На перекуре", { exact: true })).toBeVisible();
  expect(fixture.actions[0].body.break_kind).toBe("smoke");
  await page.reload();
  await expect(page.getByText("На перекуре", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Вернуться/ }).click();
  await expect(
    page.getByRole("button", { name: "На перекур", exact: true }),
  ).toBeVisible();
  expect(fixture.actions.slice(-1)[0]!.path).toContain("/end_break");
});
test("friends show marked smoke status and accept requests", async ({
  page,
}, info) => {
  const fixture = await socialFixture(page, { longName: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await expect(
    page.getByText("На перекуре с 12:45", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Принять заявку от Мария Волкова" })
    .click();
  await expect(
    page.getByRole("button", { name: /Мария Волкова.*Без активной отметки/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("friends-long-name.png"),
    fullPage: false,
  });
  expect(fixture.actions.some((item) => item.path.endsWith("/accept"))).toBe(
    true,
  );
});
test("incoming invite waits through onboarding and asks before creating request", async ({
  page,
}) => {
  const fixture = await socialFixture(page, { onboarding: true });
  await page.goto("/?invite=" + INVITE);
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Приглашение в друзья" }),
  ).toBeVisible();
  expect(
    fixture.actions.some((item) => item.path === "/api/v1/social/requests"),
  ).toBe(false);
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Люди", exact: true }),
  ).toBeVisible();
  expect(
    fixture.actions.find((item) => item.path === "/api/v1/social/requests")
      ?.body.invite_token,
  ).toBe(INVITE);
});
test("expired invite has a useful error and can be dismissed", async ({
  page,
}) => {
  await socialFixture(page, { expired: true });
  await page.goto("/?invite=" + INVITE);
  await expect(page.getByRole("alert")).toContainText("устарела");
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
});
test("leaderboard uses chosen period, public opt-in and own place outside current page", async ({
  page,
}, info) => {
  const fixture = await socialFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await page.getByRole("tab", { name: "Рейтинг", exact: true }).click();
  await expect(
    page.getByText("В общем рейтинге вы участвуете по желанию.", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Включить участие", exact: true })
    .click();
  await expect(page.getByText("Моё место", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Период рейтинга").locator("option")).toHaveText(
    ["Эта неделя", "30 дней", "Всё время"],
  );
  await page.getByLabel("Период рейтинга").selectOption("month");
  await expect
    .poll(
      () =>
        fixture.actions
          .filter((item) => item.path.endsWith("/leaderboard"))
          .slice(-1)[0]?.search,
    )
    .toContain("period=month");
  await page.getByLabel("Период рейтинга").selectOption("all");
  await expect
    .poll(
      () =>
        fixture.actions
          .filter((item) => item.path.endsWith("/leaderboard"))
          .slice(-1)[0]?.search,
    )
    .toContain("period=all");
  await page.screenshot({
    path: info.outputPath("leaderboard.png"),
    fullPage: false,
  });
});
test("friend deletion retry retains original membership precondition", async ({
  page,
}) => {
  const fixture = await socialFixture(page, { renewDuringDelete: true });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await page
    .getByRole("button", { name: /Дмитрий Михайлов.*На перекуре/ })
    .click();
  await page
    .getByRole("button", { name: "Удалить из друзей", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Дружба изменилась");
  const deleted = fixture.actions.filter((item) =>
    item.path.includes("/social/friends/"),
  );
  expect(deleted).toHaveLength(2);
  expect(deleted[0].search).toBe(deleted[1].search);
  expect(deleted[1].search).toContain(EDGE);
});
test("Telegram BackButton dismisses modal before navigating", async ({
  page,
}) => {
  await socialFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await page.evaluate(() => (window as any).__taktTest.back());
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Отметиться", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => (window as any).__taktTest.back());
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
test("safe areas and keyboard shrink retain accessible sheet controls", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await socialFixture(page, { insets: true });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
  expect(
    await page
      .locator("main")
      .evaluate((element) => parseFloat(getComputedStyle(element).paddingTop)),
  ).toBeGreaterThanOrEqual(36);
  await page.getByRole("button", { name: "Отметиться", exact: true }).click();
  await page
    .getByRole("button", { name: "Указать время Пришёл раньше" })
    .click();
  await page.locator('input[type="datetime-local"]').focus();
  await page.evaluate(() => {
    const tg = (window as any).__taktTest;
    tg.app.viewportHeight = 350;
    tg.emit("viewportChanged");
  });
  await expect(page.locator("html")).toHaveAttribute("data-keyboard", "open");
  const submit = page.getByRole("button", {
    name: "Отметить приход",
    exact: true,
  });
  await submit.scrollIntoViewIfNeeded();
  await expect(submit).toBeInViewport();
  const bounds = await submit.boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(350);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("keyboard-sheet.png"),
    fullPage: false,
  });
});
test("social polling stops while Telegram is inactive", async ({ page }) => {
  await page.clock.install();
  const fixture = await socialFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await expect.poll(() => fixture.counts.friends).toBe(1);
  await page.clock.runFor(31_000);
  await expect.poll(() => fixture.counts.friends).toBeGreaterThanOrEqual(2);
  await page.evaluate(() => (window as any).__taktTest.emit("deactivated"));
  const before = fixture.counts.friends;
  await page.clock.runFor(65_000);
  expect(fixture.counts.friends).toBe(before);
});
test("dark Telegram theme and reduced motion are respected", async ({
  page,
}, info) => {
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await socialFixture(page, { dark: true });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page
      .getByRole("heading", { name: "Мой день", exact: true })
      .evaluate((element) => getComputedStyle(element).color),
  ).toBe("rgb(237, 244, 239)");
  await page.getByRole("button", { name: "Отметиться", exact: true }).click();
  expect(
    await page
      .getByRole("dialog")
      .evaluate((element) => getComputedStyle(element).animationName),
  ).toBe("none");
  await page.screenshot({
    path: info.outputPath("dark-sheet.png"),
    fullPage: false,
  });
});

test("public ranking can be disabled in settings and tabs work with keyboard", async ({
  page,
}) => {
  await socialFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  const consent = page.getByRole("checkbox", { name: /Общий рейтинг/ });
  await expect(consent).not.toBeChecked();
  await consent.check();
  const theme = page.getByLabel("Тема приложения");
  await expect(theme).toHaveValue("dark");
  await theme.selectOption("light");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(
    page.getByText("Настройки сохранены", { exact: true }).first(),
  ).toBeAttached();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(consent).toBeChecked();
  await consent.uncheck();
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await page.getByRole("button", { name: "Люди", exact: true }).click();
  await page.getByRole("tab", { name: "Друзья", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Рейтинг", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Включить участие", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Home");
  await expect(
    page.getByRole("tab", { name: "Друзья", exact: true }),
  ).toBeFocused();
});
