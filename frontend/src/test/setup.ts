import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Register cleanup from the setup file so it is always the first afterEach
// hook. With ordered hooks, components and polling effects are gone before a
// test file restores global fetch/timer mocks.
afterEach(() => cleanup());
