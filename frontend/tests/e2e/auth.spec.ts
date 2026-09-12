import { expect, test } from "@playwright/test";

test("required-auth deployment shows a usable sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
});

test("invalid credentials show one safe error", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email").fill("unknown@example.test");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "That email and password did not match an account.",
  );
  await expect(page.getByRole("alert")).not.toContainText("user");
});
