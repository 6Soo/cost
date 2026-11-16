// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
  window.localStorage.removeItem("cost-theme");
});

it("suppresses theme transitions through paint and cleans up rapid changes/unmount", () => {
  const frames = new Map<number, FrameRequestCallback>();
  let nextFrame = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  const paint = () => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach(callback => callback(0));
  };
  const { unmount } = render(<AppShell role="owner" trips={[]} path="/">합성</AppShell>);
  const toggle = () => fireEvent.click(screen.getAllByRole("button", { name: /모드로 전환/ })[0]);
  toggle();
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(window.localStorage.getItem("cost-theme")).toBe("dark");
  expect(document.querySelectorAll("[data-cost-theme-swap]")).toHaveLength(1);
  paint();
  expect(document.querySelector("[data-cost-theme-swap]")).not.toBeNull();
  toggle();
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  paint();
  paint();
  expect(document.querySelector("[data-cost-theme-swap]")).toBeNull();
  toggle();
  unmount();
  expect(frames.size).toBe(0);
  expect(document.querySelector("[data-cost-theme-swap]")).toBeNull();
});
