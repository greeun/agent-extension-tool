import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { RemoveWizard } from "../../../src/tui/wizards/RemoveWizard.js";

describe("RemoveWizard", () => {
  const defaultProps = {
    pluginId: "my-awesome-plugin",
    installPath: "/home/user/.claude/plugins/my-awesome-plugin",
    onDone: () => {},
    onCancel: () => {},
  };

  test("pluginId가 메시지에 표시된다", () => {
    const { lastFrame } = render(<RemoveWizard {...defaultProps} />);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("my-awesome-plugin");
  });

  test("installPath가 메시지에 표시된다", () => {
    const { lastFrame } = render(<RemoveWizard {...defaultProps} />);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("/home/user/.claude/plugins/my-awesome-plugin");
  });

  test("'y:confirm  n:cancel' 힌트가 있다", () => {
    const { lastFrame } = render(<RemoveWizard {...defaultProps} />);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("y:confirm  n:cancel");
  });

  test("onCancel 콜백 prop이 수용된다", () => {
    const onCancel = mock(() => {});
    expect(() => {
      render(
        <RemoveWizard
          pluginId="test-plugin"
          installPath="/tmp/test-plugin"
          onDone={() => {}}
          onCancel={onCancel}
        />
      );
    }).not.toThrow();
  });

  test("다른 pluginId와 installPath로도 올바르게 렌더링된다", () => {
    const { lastFrame } = render(
      <RemoveWizard
        pluginId="another-plugin"
        installPath="/usr/local/plugins/another-plugin"
        onDone={() => {}}
        onCancel={() => {}}
      />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("another-plugin");
    expect(frame).toContain("/usr/local/plugins/another-plugin");
  });

  test("Remove 키워드가 메시지에 포함된다", () => {
    const { lastFrame } = render(<RemoveWizard {...defaultProps} />);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Remove");
  });
});
