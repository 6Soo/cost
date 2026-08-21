using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Automation;
using System.Windows.Forms;
using System.Windows;

internal static class AgodaNativeWindow
{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(
        IntPtr hWnd,
        IntPtr processId
    );

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(
        uint sourceThreadId,
        uint targetThreadId,
        bool attach
    );

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SetActiveWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SetFocus(IntPtr hWnd);

    public static bool FocusWindow(IntPtr hWnd)
    {
        if (hWnd == IntPtr.Zero)
        {
            return false;
        }
        IntPtr foreground = GetForegroundWindow();
        uint currentThread = GetCurrentThreadId();
        uint foregroundThread = GetWindowThreadProcessId(foreground, IntPtr.Zero);
        uint targetThread = GetWindowThreadProcessId(hWnd, IntPtr.Zero);
        bool foregroundAttached = false;
        bool targetAttached = false;
        try
        {
            if (foregroundThread != 0 && foregroundThread != currentThread)
            {
                foregroundAttached = AttachThreadInput(
                    currentThread,
                    foregroundThread,
                    true
                );
            }
            if (targetThread != 0 && targetThread != currentThread)
            {
                targetAttached = AttachThreadInput(
                    currentThread,
                    targetThread,
                    true
                );
            }
            ShowWindowAsync(hWnd, 9);
            BringWindowToTop(hWnd);
            SetForegroundWindow(hWnd);
            SetActiveWindow(hWnd);
            SetFocus(hWnd);
            Thread.Sleep(80);
            return GetForegroundWindow() == hWnd;
        }
        finally
        {
            if (targetAttached)
            {
                AttachThreadInput(currentThread, targetThread, false);
            }
            if (foregroundAttached)
            {
                AttachThreadInput(currentThread, foregroundThread, false);
            }
        }
    }

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern void mouse_event(
        uint dwFlags,
        uint dx,
        uint dy,
        uint dwData,
        UIntPtr dwExtraInfo
    );
}

internal static class Program
{
    private static readonly string RoleButton = "\uB2E8\uCD94";
    private static readonly string RoleTabItem = "\uD0ED \uD56D\uBAA9";
    private static readonly string RoleGroup = "\uADF8\uB8F9";
    private static readonly string RoleText = "\uD14D\uC2A4\uD2B8";
    private static readonly string RoleLink = "\uB9C1\uD06C";
    private static readonly string RoleEdit = "\uD14D\uC2A4\uD2B8 \uD544\uB4DC";
    private static readonly string RolePane = "\uCC3D";
    private static readonly string RoleDocument = "\uBB38\uC11C";
    private static readonly string RoleList = "\uBAA9\uB85D";
    private static readonly string RoleListItem = "\uBAA9\uB85D \uD56D\uBAA9";
    private static readonly string RoleImage = "\uC774\uBBF8\uC9C0";
    private static readonly string RoleDefault = "\uAE30\uBCF8";

    private static readonly HashSet<string> AllowlistedErrors = new HashSet<string>(
        new string[]
        {
            "window_not_found",
            "browser_omnibox_missing_or_ambiguous",
            "browser_content_root_missing_or_ambiguous",
            "semantic_action_target_missing_or_ambiguous",
            "element_not_found",
            "element_not_selectable",
            "window_not_focused",
            "browser_omnibox_not_focused",
            "unsupported_hotkey",
            "unsupported_key",
            "focused_value_receiver_missing"
        },
        StringComparer.Ordinal
    );

    private static void WriteResult(object value)
    {
        var serializer = new JavaScriptSerializer();
        Console.Out.WriteLine(serializer.Serialize(value));
    }

    private static string GetNormalizedName(AutomationElement element)
    {
        string name = element.Current.Name ?? string.Empty;
        name = Regex.Replace(name, @"[\r\n]+", " ");
        name = Regex.Replace(name, @"\s+", " ");
        return name.Trim();
    }

    private static string GetTextSha256(string value)
    {
        using (var sha = SHA256.Create())
        {
            byte[] bytes = new UTF8Encoding(false).GetBytes(value);
            byte[] hash = sha.ComputeHash(bytes);
            var sb = new StringBuilder(hash.Length * 2);
            for (int i = 0; i < hash.Length; i++)
            {
                sb.Append(hash[i].ToString("x2"));
            }
            return sb.ToString();
        }
    }

    private static bool TestActionable(AutomationElement element, string mode)
    {
        if (!element.Current.IsEnabled)
        {
            return false;
        }
        object pattern;
        if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out pattern))
        {
            return true;
        }
        if (mode == "click" && element.TryGetCurrentPattern(InvokePattern.Pattern, out pattern))
        {
            return true;
        }
        return false;
    }

    private static bool TryGetCoordinatePoint(
        AutomationElement element,
        out Point point
    )
    {
        point = new Point();
        try
        {
            if (element.TryGetClickablePoint(out point))
            {
                return true;
            }
        }
        catch (ElementNotAvailableException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            // Fall through to the current visible bounds.
        }

        try
        {
            Rect bounds = element.Current.BoundingRectangle;
            if (
                bounds.IsEmpty
                || bounds.Width <= 0
                || bounds.Height <= 0
            )
            {
                return false;
            }
            point = new Point(
                bounds.Left + (bounds.Width / 2.0),
                bounds.Top + (bounds.Height / 2.0)
            );
            return true;
        }
        catch (ElementNotAvailableException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    private static bool CoordinateClick(
        AutomationElement element,
        IntPtr windowHandle,
        Point point
    )
    {
        if (!element.Current.IsEnabled)
        {
            return false;
        }
        if (!AgodaNativeWindow.FocusWindow(windowHandle))
        {
            return false;
        }
        if (!AgodaNativeWindow.SetCursorPos(
            (int)Math.Round(point.X),
            (int)Math.Round(point.Y)
        ))
        {
            return false;
        }
        Thread.Sleep(40);
        const uint MouseEventLeftDown = 0x0002;
        const uint MouseEventLeftUp = 0x0004;
        AgodaNativeWindow.mouse_event(
            MouseEventLeftDown,
            0,
            0,
            0,
            UIntPtr.Zero
        );
        AgodaNativeWindow.mouse_event(
            MouseEventLeftUp,
            0,
            0,
            0,
            UIntPtr.Zero
        );
        return true;
    }

    private static AutomationElement GetOmnibox(AutomationElement root)
    {
        var condition = new PropertyCondition(
            AutomationElement.ControlTypeProperty,
            ControlType.Edit
        );
        var matches = root.FindAll(TreeScope.Descendants, condition);
        var filtered = new List<AutomationElement>();
        foreach (AutomationElement el in matches)
        {
            if (el.Current.ClassName == "OmniboxViewViews")
            {
                filtered.Add(el);
            }
        }
        if (filtered.Count != 1)
        {
            throw new InvalidOperationException("browser_omnibox_missing_or_ambiguous");
        }
        return filtered[0];
    }

    private static AutomationElement GetContentRoot(AutomationElement root)
    {
        var condition = new PropertyCondition(
            AutomationElement.AutomationIdProperty,
            "RootWebArea"
        );
        var matches = root.FindAll(TreeScope.Descendants, condition);
        var filtered = new List<AutomationElement>();
        foreach (AutomationElement el in matches)
        {
            if (!el.Current.IsOffscreen)
            {
                filtered.Add(el);
            }
        }
        if (filtered.Count != 1)
        {
            throw new InvalidOperationException("browser_content_root_missing_or_ambiguous");
        }
        return filtered[0];
    }

    private static string GetRole(AutomationElement element)
    {
        string kind = element.Current.ControlType.ProgrammaticName;
        switch (kind)
        {
            case "ControlType.Button": return RoleButton;
            case "ControlType.TabItem": return RoleTabItem;
            case "ControlType.Group": return RoleGroup;
            case "ControlType.Text": return RoleText;
            case "ControlType.Hyperlink": return RoleLink;
            case "ControlType.Edit": return RoleEdit;
            case "ControlType.Pane": return RolePane;
            case "ControlType.Document": return RoleDocument;
            case "ControlType.List": return RoleList;
            case "ControlType.ListItem": return RoleListItem;
            case "ControlType.Image": return RoleImage;
            default: return RoleDefault;
        }
    }

    private sealed class TreeData
    {
        public List<AutomationElement> Nodes { get; set; }
        public string TreeText { get; set; }
    }

    private static void VisitTree(
        AutomationElement parent,
        int depth,
        TreeWalker walker,
        List<AutomationElement> nodes,
        List<string> lines,
        ref int counter
    )
    {
        AutomationElement child = null;
        try
        {
            child = walker.GetFirstChild(parent);
        }
        catch (ElementNotAvailableException)
        {
            return;
        }
        while (child != null)
        {
            AutomationElement next = null;
            try
            {
                next = walker.GetNextSibling(child);
            }
            catch (ElementNotAvailableException)
            {
                // A dynamic Chromium node vanished. The already captured next
                // sibling boundary is unavailable, so this branch ends safely.
            }

            try
            {
                int index = counter;
                counter++;
                nodes.Add(child);
                string name = GetNormalizedName(child);
                string automationId = (child.Current.AutomationId ?? string.Empty);
                automationId = Regex.Replace(automationId, @"[\r\n]+", " ").Trim();
                if (automationId.StartsWith("mmb-booking-card--", StringComparison.Ordinal))
                {
                    name = automationId;
                }
                if (name.Length > 0)
                {
                    string indent = new string(' ', depth * 2);
                    string role = GetRole(child);
                    lines.Add(string.Format("{0}{1} {2} {3}", indent, index, role, name));
                    if (
                        child.Current.ControlType == ControlType.Button &&
                        Regex.IsMatch(name, @"^\d+$") &&
                        !child.Current.IsEnabled
                    )
                    {
                        lines.Add(string.Format("{0}{1} {2} {3}", indent, index, RoleDefault, name));
                    }
                    if (child.Current.ControlType == ControlType.TabItem)
                    {
                        object selection;
                        if (
                            child.TryGetCurrentPattern(SelectionItemPattern.Pattern, out selection) &&
                            ((SelectionItemPattern)selection).Current.IsSelected
                        )
                        {
                            lines.Add(string.Format("{0}{1} {2} {3}", indent, index, RoleDefault, name));
                        }
                    }
                }
                VisitTree(child, depth + 1, walker, nodes, lines, ref counter);
            }
            catch (ElementNotAvailableException)
            {
                // Dynamic browser UI can disappear between sibling discovery
                // and property reads. Skip only that transient subtree.
            }
            child = next;
        }
    }

    private static TreeData GetTreeData(AutomationElement root)
    {
        var walker = TreeWalker.RawViewWalker;
        var nodes = new List<AutomationElement>();
        var lines = new List<string>();
        int counter = 0;

        VisitTree(root, 0, walker, nodes, lines, ref counter);
        return new TreeData
        {
            Nodes = nodes,
            TreeText = string.Join("\n", lines.ToArray())
        };
    }

    [STAThread]
    public static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        string operation = null;
        long windowId = 0;
        int elementIndex = -1;
        string text = string.Empty;
        string key = string.Empty;
        string expectedNameSha256 = string.Empty;
        bool contentOnly = false;

        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            if (string.Equals(arg, "-Operation", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(arg, "--operation", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) operation = args[++i];
            }
            else if (string.Equals(arg, "-WindowId", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--window-id", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) long.TryParse(args[++i], out windowId);
            }
            else if (string.Equals(arg, "-ElementIndex", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--element-index", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) int.TryParse(args[++i], out elementIndex);
            }
            else if (string.Equals(arg, "-Text", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--text", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) text = args[++i];
            }
            else if (string.Equals(arg, "-Key", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--key", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) key = args[++i];
            }
            else if (string.Equals(arg, "-ExpectedNameSha256", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--expected-name-sha256", StringComparison.OrdinalIgnoreCase))
            {
                if (i + 1 < args.Length) expectedNameSha256 = args[++i];
            }
            else if (string.Equals(arg, "-ContentOnly", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(arg, "--content-only", StringComparison.OrdinalIgnoreCase))
            {
                contentOnly = true;
            }
        }

        Dictionary<string, object> actionDiagnostic = null;
        try
        {
            if (string.IsNullOrEmpty(operation) || windowId == 0)
            {
                throw new InvalidOperationException("window_not_found");
            }

            AutomationElement root = AutomationElement.FromHandle((IntPtr)windowId);
            if (root == null)
            {
                throw new InvalidOperationException("window_not_found");
            }

            AutomationElement treeRoot = contentOnly ? GetContentRoot(root) : root;

            if (operation == "state")
            {
                TreeData tree = GetTreeData(treeRoot);
                var snapshot = new Dictionary<string, object>();
                snapshot.Add("treeText", tree.TreeText);
                var result = new Dictionary<string, object>();
                result.Add("snapshot", snapshot);
                var response = new Dictionary<string, object>();
                response.Add("ok", true);
                response.Add("result", result);
                WriteResult(response);
                return 0;
            }

            if (operation == "click" || operation == "select")
            {
                TreeData tree = GetTreeData(treeRoot);
                AutomationElement element = null;
                bool coordinatePointAvailable = false;
                Point coordinatePoint = new Point();
                if (!string.IsNullOrEmpty(expectedNameSha256))
                {
                    if (elementIndex < 0 || elementIndex >= tree.Nodes.Count)
                    {
                        throw new InvalidOperationException("element_not_found");
                    }

                    element = tree.Nodes[elementIndex];
                    string controlType = element.Current.ControlType == null
                        ? "unknown"
                        : element.Current.ControlType.ProgrammaticName;
                    bool nameMatches = string.Equals(
                        GetTextSha256(GetNormalizedName(element)),
                        expectedNameSha256,
                        StringComparison.OrdinalIgnoreCase
                    );
                    int nameMatchCount = nameMatches ? 1 : 0;
                    int enabledNameMatchCount = 0;
                    int selectionPatternMatchCount = 0;
                    int invokePatternMatchCount = 0;
                    bool hasSelectionPattern = false;
                    bool hasInvokePattern = false;
                    bool hasCoordinatePoint = false;
                    if (nameMatches && element.Current.IsEnabled)
                    {
                        enabledNameMatchCount = 1;
                        object selectionPattern;
                        hasSelectionPattern = element.TryGetCurrentPattern(
                            SelectionItemPattern.Pattern,
                            out selectionPattern
                        );
                        if (hasSelectionPattern)
                        {
                            selectionPatternMatchCount = 1;
                        }
                        if (operation == "click")
                        {
                            object invokePattern;
                            hasInvokePattern = element.TryGetCurrentPattern(
                                InvokePattern.Pattern,
                                out invokePattern
                            );
                            if (hasInvokePattern)
                            {
                                invokePatternMatchCount = 1;
                            }
                        }
                        if (
                            (
                                controlType == "ControlType.Button"
                                || controlType == "ControlType.Hyperlink"
                            )
                            && (
                                operation == "click"
                                || (
                                    operation == "select"
                                    && Regex.IsMatch(
                                        GetNormalizedName(element),
                                        @"^\d+$"
                                    )
                                )
                            )
                        )
                        {
                            hasCoordinatePoint = TryGetCoordinatePoint(
                                element,
                                out coordinatePoint
                            );
                            coordinatePointAvailable = hasCoordinatePoint;
                        }
                    }
                    bool actionable = enabledNameMatchCount == 1 &&
                        (
                            hasSelectionPattern
                            || (operation == "click" && hasInvokePattern)
                            || hasCoordinatePoint
                        );
                    if (!nameMatches || !actionable)
                    {
                        actionDiagnostic = new Dictionary<string, object>();
                        actionDiagnostic.Add(
                            "failure_stage",
                            nameMatches ? "actionable_filter" : "stale_hash"
                        );
                        actionDiagnostic.Add("name_match_count", nameMatchCount);
                        actionDiagnostic.Add("enabled_name_match_count", enabledNameMatchCount);
                        actionDiagnostic.Add("selection_pattern_match_count", selectionPatternMatchCount);
                        actionDiagnostic.Add("invoke_pattern_match_count", invokePatternMatchCount);
                        actionDiagnostic.Add(
                            "coordinate_point_match_count",
                            hasCoordinatePoint ? 1 : 0
                        );
                        actionDiagnostic.Add("actionable_candidate_count", actionable ? 1 : 0);
                        var controlTypeCounts = new Dictionary<string, int>(StringComparer.Ordinal);
                        controlTypeCounts.Add(controlType, 1);
                        actionDiagnostic.Add("control_type_counts", controlTypeCounts);
                        throw new InvalidOperationException("semantic_action_target_missing_or_ambiguous");
                    }
                }
                else
                {
                    if (elementIndex < 0 || elementIndex >= tree.Nodes.Count)
                    {
                        throw new InvalidOperationException("element_not_found");
                    }
                    element = tree.Nodes[elementIndex];
                }

                object pattern;
                if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out pattern))
                {
                    ((SelectionItemPattern)pattern).Select();
                }
                else if (operation == "click" && element.TryGetCurrentPattern(InvokePattern.Pattern, out pattern))
                {
                    ((InvokePattern)pattern).Invoke();
                }
                else if (
                    !string.IsNullOrEmpty(expectedNameSha256)
                    && (
                        element.Current.ControlType == ControlType.Button
                        || element.Current.ControlType == ControlType.Hyperlink
                    )
                    && (
                        operation == "click"
                        || (
                            operation == "select"
                            && Regex.IsMatch(
                                GetNormalizedName(element),
                                @"^\d+$"
                            )
                        )
                    )
                    && coordinatePointAvailable
                    && CoordinateClick(element, (IntPtr)windowId, coordinatePoint)
                )
                {
                    // The Chromium UIA provider exposes these buttons without
                    // SelectionItem/InvokePattern.  The element index and
                    // exact name hash were already bound above; coordinate
                    // activation is therefore limited to that one element.
                }
                else
                {
                    throw new InvalidOperationException("element_not_selectable");
                }

                var result = new Dictionary<string, object>();
                result.Add("action", operation);
                var response = new Dictionary<string, object>();
                response.Add("ok", true);
                response.Add("result", result);
                WriteResult(response);
                return 0;
            }

            IntPtr windowHandle = (IntPtr)windowId;
            if (!AgodaNativeWindow.FocusWindow(windowHandle))
            {
                throw new InvalidOperationException("window_not_focused");
            }

            if (operation == "hotkey")
            {
                switch (key)
                {
                    case "CmdOrCtrl+L":
                        AutomationElement omnibox = GetOmnibox(root);
                        omnibox.SetFocus();
                        Thread.Sleep(40);
                        AutomationElement focused = AutomationElement.FocusedElement;
                        if (focused == null || focused.Current.ClassName != "OmniboxViewViews")
                        {
                            throw new InvalidOperationException("browser_omnibox_not_focused");
                        }
                        break;
                    case "CmdOrCtrl+R":
                        SendKeys.SendWait("^r");
                        break;
                    case "Alt+Left":
                        SendKeys.SendWait("%{LEFT}");
                        break;
                    default:
                        throw new InvalidOperationException("unsupported_hotkey");
                }
            }
            else if (operation == "press")
            {
                switch (key)
                {
                    case "Return":
                        SendKeys.SendWait("{ENTER}");
                        break;
                    case "Escape":
                        SendKeys.SendWait("{ESC}");
                        break;
                    default:
                        throw new InvalidOperationException("unsupported_key");
                }
            }
            else if (operation == "type")
            {
                AutomationElement focused = GetOmnibox(root);
                object valuePattern;
                if (focused.TryGetCurrentPattern(ValuePattern.Pattern, out valuePattern))
                {
                    ((ValuePattern)valuePattern).SetValue(text);
                }
                else
                {
                    throw new InvalidOperationException("focused_value_receiver_missing");
                }
            }
            else
            {
                throw new InvalidOperationException("bridge_execution_failed");
            }

            var res = new Dictionary<string, object>();
            res.Add("action", operation);
            var resp = new Dictionary<string, object>();
            resp.Add("ok", true);
            resp.Add("result", res);
            WriteResult(resp);
            return 0;
        }
        catch (Exception ex)
        {
            string code = "bridge_execution_failed";
            if (ex != null && AllowlistedErrors.Contains(ex.Message))
            {
                code = ex.Message;
            }
            var err = new Dictionary<string, object>();
            err.Add("code", code);
            if (actionDiagnostic != null)
            {
                err.Add("diagnostic", actionDiagnostic);
            }
            var resp = new Dictionary<string, object>();
            resp.Add("ok", false);
            resp.Add("error", err);
            WriteResult(resp);
            return 1;
        }
    }
}
