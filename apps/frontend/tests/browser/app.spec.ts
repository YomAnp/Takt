import { test, expect, type Page } from "@playwright/test";

const profile = {
  id: "11111111-1111-4111-8111-111111111111",
  display_name: "Александр",
  telegram_id: 123,
  telegram_username: "alexander",
  role: "member",
  is_active: true,
  onboarded: true,
  end_time: "18:00:00",
};
const summary = {
  work_date: "2026-10-27",
  time_zone: "Europe/Moscow",
  as_of: "2026-10-27T12:00:00Z",
  state: "not_started",
  scheduled_end_at: "2026-10-27T15:00:00Z",
  seconds_until_end: 10800,
  total_seconds: 0,
  break_seconds: 0,
  overtime_seconds: 0,
  confirmed_seconds: 0,
  is_provisional: false,
};
async function fixture(
  page: Page,
  options: {
    onboarding?: boolean;
    role?: string;
    pending?: boolean;
    failOnce?: boolean;
  } = {},
) {
  let user = {
    ...profile,
    onboarded: !options.onboarding,
    role: options.role || "member",
  };
  let record: any = options.pending
    ? {
        id: "22222222-2222-4222-8222-222222222222",
        revision: 1,
        started_at: "2026-10-26T06:00:00Z",
        ended_at: null,
        breaks: [],
      }
    : null;
  const calls: Array<{ operation: string; body: any }> = [];
  let managed = { ...profile, id: "33333333-3333-4333-8333-333333333333" };
  let failed = false;
  await page.route("https://telegram.org/js/**", (route) =>
    route.fulfill({ body: "" }),
  );
  await page.addInitScript(() => {
    (window as any).Telegram = {
      WebApp: { initData: "signed-test-fixture", ready() {}, expand() {} },
    };
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const respond = (body: any) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path.endsWith("/auth/telegram"))
      return respond({ token: "test-session", profile: user });
    if (path.endsWith("/preferences")) {
      user = { ...user, ...route.request().postDataJSON(), onboarded: true };
      return respond(user);
    }
    if (path.endsWith("/state"))
      return respond({
        now: "2026-10-27T12:00:00Z",
        time_zone: "Europe/Moscow",
        attendance: record,
        last_finished: null,
        summary: {
          ...summary,
          state: record ? "working" : "not_started",
          total_seconds: record ? 21600 : 0,
          is_provisional: !!record,
        },
        pending: options.pending
          ? {
              work_date: "2026-10-26",
              attendance: record,
              scheduled_end_at: "2026-10-26T15:00:00Z",
              can_use_scheduled_end: true,
            }
          : null,
      });
    if (path.endsWith("/preview"))
      return respond({
        attendance: record,
        proposed_end_at:
          route.request().postDataJSON().occurred_at || "2026-10-27T12:00:00Z",
        will_end_break: false,
        summary: { ...summary, total_seconds: 32400, state: "finished" },
      });
    if (path.includes("/attendance/")) {
      const operation = path.split("/").pop()!;
      const body = route.request().postDataJSON();
      calls.push({ operation, body });
      if (options.failOnce && !failed) {
        failed = true;
        return route.abort("failed");
      }
      record =
        operation === "check_in"
          ? {
              id: "22222222-2222-4222-8222-222222222222",
              revision: 1,
              started_at: body.occurred_at || "2026-10-27T12:00:00Z",
              ended_at: null,
              breaks: [],
            }
          : null;
      options.pending = false;
      return respond({
        request_id: body.request_id,
        attendance: record,
        closed_break_id: null,
      });
    }
    if (path.endsWith("/history"))
      return respond([
        {
          ...summary,
          total_seconds: 32400,
          confirmed_seconds: 32400,
          state: "finished",
        },
      ]);
    if (path.endsWith("/admin/users")) return respond([managed]);
    if (path.endsWith("/day"))
      return respond({ ...summary, total_seconds: 32400 });
    if (
      path.includes("/admin/users/") &&
      route.request().method() === "PATCH"
    ) {
      const body = route.request().postDataJSON();
      calls.push({ operation: "manage_user", body });
      managed = { ...managed, ...body };
      return respond(managed);
    }
    return respond(user);
  });
  return calls;
}
test("onboarding saves settings without starting attendance", async ({
  page,
}) => {
  const calls = await fixture(page, { onboarding: true });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Привет. Это Такт." }),
  ).toBeVisible();
  await page.getByLabel("Как к вам обращаться").fill("Мария");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
  expect(calls).toHaveLength(0);
});
test("earlier arrival uses actual time and one request id on retry", async ({
  page,
}) => {
  const calls = await fixture(page, { failOnce: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Отметиться", exact: true }).click();
  await page
    .getByRole("button", { name: "Указать время Пришёл раньше" })
    .click();
  await page.locator('input[type="datetime-local"]').fill("2026-10-27T09:00");
  await page
    .getByRole("button", { name: "Отметить приход", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Завершить день", exact: true }),
  ).toBeVisible();
  expect(calls).toHaveLength(2);
  expect(calls[0].body.request_id).toBe(calls[1].body.request_id);
  expect(calls[1].body.occurred_at).toBe("2026-10-27T06:00:00.000Z");
});
test("missed departure needs preview and explicit confirmation", async ({
  page,
}) => {
  const calls = await fixture(page, { pending: true });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Указать время ухода", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Посмотреть итог", exact: true })
    .click();
  expect(calls).toHaveLength(0);
  await expect(
    page.getByRole("dialog").getByText("09:00", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Подтвердить уход", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
  expect(calls[0].body.confirmed).toBe(true);
  expect(calls[0].body.occurred_at).toBe("2026-10-26T15:00:00Z");
});
test("mobile layout fits a narrow phone and supports keyboard closing", async ({
  page,
}, info) => {
  await fixture(page);
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Отметиться", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("day-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Отметиться", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
test("owner can open real user management while members cannot see it", async ({
  page,
}, info) => {
  await fixture(page, { role: "superadmin" });
  await page.goto("/");
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await page.getByRole("button", { name: "Пользователи", exact: true }).click();
  await page.getByRole("button", { name: /Александр.*alexander/ }).click();
  await expect(
    page.getByRole("button", {
      name: "Назначить администратором",
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("admin-mobile.png"),
    fullPage: true,
  });
});

test("members have no user-management control", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Пользователи", exact: true }),
  ).toHaveCount(0);
});

test("owner appoints and removes an administrator through confirmation", async ({
  page,
}) => {
  const calls = await fixture(page, { role: "superadmin" });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await page.getByRole("button", { name: "Пользователи", exact: true }).click();
  await page.getByRole("button", { name: /Александр.*alexander/ }).click();
  await page
    .getByRole("button", { name: "Назначить администратором", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Снять права администратора",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Снять права администратора", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Назначить администратором",
      exact: true,
    }),
  ).toBeVisible();
  expect(calls.map((call) => call.body.role)).toEqual(["admin", "member"]);
});
