using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace LoginShell
{
    internal static class Trace
    {
        public static bool Enabled { get; set; } = true;

        private static readonly string TracePath =
            Path.Combine(Path.GetTempPath(), "wb-shell-login.trace.txt");

        public static void Log(string message)
        {
            if (Enabled)
            {
                Write(message);
            }
        }

        // 产品模式会关掉 Enabled；失败诊断必须落盘，绕开开关但共用同一个文件。
        public static void LogAlways(string message)
        {
            Write(message);
        }

        public static string XhsId(string value)
        {
            return value != null && System.Text.RegularExpressions.Regex.IsMatch(value, @"\A[A-Za-z0-9_-]{1,100}\z")
                ? value : "-";
        }

        public static bool IsXhsOperationId(string value)
        {
            return value != null && System.Text.RegularExpressions.Regex.IsMatch(value, @"\A[0-9a-f]{32}\z");
        }

        private static void Write(string message)
        {
            try
            {
                File.AppendAllText(
                    TracePath,
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + message + Environment.NewLine,
                    new UTF8Encoding(false));
            }
            catch
            {
                // tracing must never throw
            }
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            AppDomain.CurrentDomain.UnhandledException += (sender, e) =>
            {
                Trace.Log("unhandled: " + e.ExceptionObject);
            };
            Application.ThreadException += (sender, e) =>
            {
                Trace.Log("unhandled-thread: " + e.Exception);
            };

            // --diagnose：不等人操作。自动回到记住的收藏页 → 跑一轮拟人滚动 → 写诊断 → 退出。
            // 目的是让"抓到的条数对不对"这类问题可以自己验证，不必每次请人手动点。
            bool diagnose = false;
            // --silent-window：批量取正文时不要每 45 秒抢一次焦点。
            // 启动即最小化 + 不置顶 + 不显示任务栏按钮，页面照常导航与执行脚本。
            bool silentWindow = false;
            string extractUrls = null;
            int extractLimit = 10;
            int extractDelayMin = 25;
            int extractDelayMax = 60;
            // --eval <js>：在已登录页面上下文里执行一段 JS，把返回值写到 --eval-out。
            // 用途：借签名时让页面替我们调 window._webmsxyw / 发 fetch，请求由浏览器发出，
            // TLS 指纹与 Cookie 都是真实的。脚本可以返回 Promise，WebView2 会等它 resolve。
            string evalJs = null;
            string evalOut = null;
            string evalNav = "https://www.xiaohongshu.com/explore";
            int evalWaitMs = 6000;
            bool productMode = false;
            string productUrl = "http://127.0.0.1:8765/";
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (string.Equals(arg, "--product", StringComparison.OrdinalIgnoreCase))
                {
                    productMode = true;
                    if (i + 1 < args.Length
                        && !args[i + 1].StartsWith("--", StringComparison.OrdinalIgnoreCase))
                    {
                        productUrl = args[++i];
                    }
                }
                else if (string.Equals(arg, "--diagnose", StringComparison.OrdinalIgnoreCase))
                {
                    diagnose = true;
                }
                else if (string.Equals(arg, "--extract", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length
                         && !args[i + 1].StartsWith("--", StringComparison.OrdinalIgnoreCase))
                {
                    extractUrls = args[i + 1];
                }
                else if (string.Equals(arg, "--urls", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    extractUrls = args[i + 1];
                }
                else if (string.Equals(arg, "--limit", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    int.TryParse(args[i + 1], out extractLimit);
                }
                else if (string.Equals(arg, "--delay-min", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    int.TryParse(args[i + 1], out extractDelayMin);
                }
                else if (string.Equals(arg, "--delay-max", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    int.TryParse(args[i + 1], out extractDelayMax);
                }
                else if (string.Equals(arg, "--eval", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    evalJs = args[i + 1];
                }
                else if (string.Equals(arg, "--eval-out", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    evalOut = args[i + 1];
                }
                else if (string.Equals(arg, "--nav", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    evalNav = args[i + 1];
                }
                else if (string.Equals(arg, "--wait", StringComparison.OrdinalIgnoreCase)
                         && i + 1 < args.Length)
                {
                    int.TryParse(args[i + 1], out evalWaitMs);
                }
                else if (string.Equals(arg, "--silent-window", StringComparison.OrdinalIgnoreCase))
                {
                    silentWindow = true;
                }
            }

            ExtractOptions extract = null;
            if (!string.IsNullOrWhiteSpace(extractUrls))
            {
                extract = new ExtractOptions
                {
                    UrlsPath = extractUrls,
                    Limit = extractLimit,
                    DelayMinSec = extractDelayMin,
                    DelayMaxSec = extractDelayMax < extractDelayMin ? extractDelayMin : extractDelayMax,
                };
            }

            EvalOptions eval = null;
            if (!string.IsNullOrWhiteSpace(evalJs))
            {
                eval = new EvalOptions
                {
                    JsPath = evalJs,
                    OutPath = string.IsNullOrWhiteSpace(evalOut)
                        ? Path.Combine(Path.GetTempPath(), "wb-shell-eval-out.txt")
                        : evalOut,
                    NavUrl = evalNav,
                    WaitMs = evalWaitMs < 1000 ? 1000 : evalWaitMs,
                };
            }

            try
            {
                if (productMode)
                {
                    Uri target;
                    if (!Uri.TryCreate(productUrl, UriKind.Absolute, out target)
                        || !target.IsLoopback
                        || (target.Scheme != Uri.UriSchemeHttp && target.Scheme != Uri.UriSchemeHttps))
                    {
                        MessageBox.Show(
                            "产品壳仅接受本机回环地址（例如 http://127.0.0.1:8765/）。",
                            "产品壳地址无效",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error);
                        return;
                    }
                }

                Trace.Enabled = !productMode;
                Trace.Log("main: enter args=" + string.Join(" ", args));
                Application.Run(new ShellForm(diagnose, extract, silentWindow, eval, productMode, productUrl));
            }
            catch (Exception ex)
            {
                Trace.Log("main: fatal " + ex);
            }

            Trace.Log("main: exit");
        }
    }

    internal sealed class CookieSnapshot
    {
        public string Name { get; set; }

        public int Count { get; set; }

        public int NonEmpty { get; set; }

        public List<string> CookieNames { get; set; } = new List<string>();

        public List<string> HttpOnlyNames { get; set; } = new List<string>();

        public List<string> LoginCookiesPresent { get; set; } = new List<string>();

        public bool LoggedIn { get; set; }
    }

    internal sealed class CapturedItem
    {
        public string Url { get; set; }

        public string Body { get; set; }
    }

    // 分页链上的一步：请求带什么 cursor、服务端回什么 cursor、还有没有更多、这一页给了几条。
    internal sealed class PageStep
    {
        public string Url { get; set; }

        public string Cursor { get; set; }

        public string NextCursor { get; set; }

        public bool? HasMore { get; set; }

        public int Count { get; set; }

        public string FirstId { get; set; }
    }

    // --extract 的运行参数。只在实验区用，产品代码不引入。
    // --eval 的运行参数：读一段 JS 文件，在已登录页面里跑，把返回值原文写盘。
    internal sealed class EvalOptions
    {
        public string JsPath { get; set; }
        public string OutPath { get; set; }
        public string NavUrl { get; set; } = "https://www.xiaohongshu.com/explore";
        public int WaitMs { get; set; } = 6000;
    }

    internal sealed class ExtractOptions
    {
        public string UrlsPath { get; set; }

        public int Limit { get; set; } = 10;

        // 真人节奏：一条笔记停留 25~60 秒随机，绝不并发、绝不匀速。
        public int DelayMinSec { get; set; } = 25;

        public int DelayMaxSec { get; set; } = 60;
    }

    internal sealed class CapturedNote
    {
        public string Platform { get; set; }

        public string Id { get; set; }

        public string Title { get; set; }

        public string Type { get; set; }

        public string Author { get; set; }

        public string Url { get; set; }
    }

    internal sealed class ScrollProbe
    {
        public string Url { get; set; }

        public int WindowY { get; set; }

        public int ViewportW { get; set; }

        public int ViewportH { get; set; }

        public int Candidates { get; set; }

        public int BestTop { get; set; }

        public int BestRoom { get; set; }

        public string BestTag { get; set; }

        public int DocHeight { get; set; }

        public bool AtBottom { get; set; }

        public string Error { get; set; }
    }

    internal sealed class ShellSessionState
    {
        public string Platform { get; set; }

        public Dictionary<string, string> FavUrls { get; set; } =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    }

    internal sealed class ShellForm : Form
    {
        private const int ProductChromeHeight = 70;
        private const int ProductChromeButtonWidth = 52;
        private const int ProductChromeButtonPanelWidth = 164;
        private const int ProductChromeGlyphMinimize = 0;
        private const int ProductChromeGlyphMaximize = 1;
        private const int ProductChromeGlyphRestore = 2;
        private const int ProductChromeGlyphClose = 3;
        private const int ProductResizeBorderLogicalPixels = 8;
        private const int WmNcHitTest = 0x0084;
        private const int WmNcLButtonDown = 0x00A1;
        private const int HtCaption = 2;
        private const int HtClient = 1;
        private const int HtTransparent = -1;
        private const int HtLeft = 10;
        private const int HtRight = 11;
        private const int HtTop = 12;
        private const int HtTopLeft = 13;
        private const int HtTopRight = 14;
        private const int HtBottom = 15;
        private const int HtBottomLeft = 16;
        private const int HtBottomRight = 17;
        private const int WsThickFrame = 0x00040000;

        private static readonly Color ProductChromeColor = Color.FromArgb(127, 69, 33);
        private static readonly Color ProductChromeText = Color.FromArgb(255, 249, 237);

        [DllImport("user32.dll")]
        private static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private sealed class ProductWebView : WebView2
        {
            public Func<Point, bool> ResizeHitTest;

            protected override void WndProc(ref Message message)
            {
                if (message.Msg == WmNcHitTest && ResizeHitTest != null
                    && ResizeHitTest(ScreenPointFromMessage(message)))
                {
                    message.Result = (IntPtr)HtTransparent;
                    return;
                }

                base.WndProc(ref message);
            }
        }

        private sealed class ProductChromePanel : Panel
        {
            public Func<Point, bool> ResizeHitTest;

            protected override void WndProc(ref Message message)
            {
                if (message.Msg == WmNcHitTest && ResizeHitTest != null
                    && ResizeHitTest(ScreenPointFromMessage(message)))
                {
                    message.Result = (IntPtr)HtTransparent;
                    return;
                }

                base.WndProc(ref message);
            }
        }

        private sealed class ProductChromeLabel : Label
        {
            public Func<Point, bool> ResizeHitTest;

            protected override void WndProc(ref Message message)
            {
                if (message.Msg == WmNcHitTest && ResizeHitTest != null
                    && ResizeHitTest(ScreenPointFromMessage(message)))
                {
                    message.Result = (IntPtr)HtTransparent;
                    return;
                }

                base.WndProc(ref message);
            }
        }

        private sealed class ProductChromeButton : Button
        {
            public int Glyph;

            protected override void OnPaint(PaintEventArgs args)
            {
                base.OnPaint(args);

                Rectangle bounds = ClientRectangle;
                if (bounds.Width <= 0 || bounds.Height <= 0)
                {
                    return;
                }

                float scale = Math.Max(1F, Math.Min(bounds.Width, bounds.Height) / 32F);
                float glyphSize = 18F * scale;
                float centerX = bounds.Left + bounds.Width / 2F;
                float centerY = bounds.Top + bounds.Height / 2F;
                float lineWidth = Math.Max(1.75F, 1.8F * scale);

                GraphicsState state = args.Graphics.Save();
                args.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                using (var pen = new Pen(ProductChromeText, lineWidth))
                {
                    switch (Glyph)
                    {
                        case ProductChromeGlyphMinimize:
                            args.Graphics.DrawLine(
                                pen,
                                centerX - glyphSize / 2F,
                                centerY + scale * 0.25F,
                                centerX + glyphSize / 2F,
                                centerY + scale * 0.25F);
                            break;
                        case ProductChromeGlyphMaximize:
                            DrawChromeSquare(args.Graphics, pen, centerX, centerY, glyphSize);
                            break;
                        case ProductChromeGlyphRestore:
                            float offset = scale * 1.6F;
                            DrawChromeSquare(args.Graphics, pen, centerX - offset, centerY + offset, glyphSize);
                            DrawChromeSquare(args.Graphics, pen, centerX + offset, centerY - offset, glyphSize);
                            break;
                        case ProductChromeGlyphClose:
                            float half = glyphSize / 2F;
                            args.Graphics.DrawLine(pen, centerX - half, centerY - half, centerX + half, centerY + half);
                            args.Graphics.DrawLine(pen, centerX + half, centerY - half, centerX - half, centerY + half);
                            break;
                    }
                }

                args.Graphics.Restore(state);
            }

            private static void DrawChromeSquare(Graphics graphics, Pen pen, float centerX, float centerY, float size)
            {
                float half = size / 2F;
                graphics.DrawRectangle(pen, centerX - half, centerY - half, size, size);
            }
        }

        private sealed class Target
        {
            public string Name;
            public string Display;
            public string HomeUrl;
            public string CookieUri;
            public string[] LoginCookies;
            public string[] FavoriteApiHints;
        }

        private static readonly Target[] Targets =
        {
            new Target
            {
                Name = "bilibili",
                Display = "B站",
                HomeUrl = "https://www.bilibili.com/",
                CookieUri = "https://www.bilibili.com/",
                LoginCookies = new[] { "SESSDATA", "bili_jct", "DedeUserID" },
                FavoriteApiHints = new[] { "fav/resource/list", "favlist", "/fav/" },
            },
            new Target
            {
                Name = "zhihu",
                Display = "知乎",
                HomeUrl = "https://www.zhihu.com/",
                CookieUri = "https://www.zhihu.com/",
                LoginCookies = new[] { "z_c0", "d_c0" },
                FavoriteApiHints = new[] { "/api/v4/collections", "/collections/", "favlists" },
            },
            new Target
            {
                Name = "xiaohongshu",
                Display = "小红书",
                HomeUrl = "https://www.xiaohongshu.com/explore",
                CookieUri = "https://www.xiaohongshu.com/",
                LoginCookies = new[] { "web_session", "a1" },
                FavoriteApiHints = new[] { "note/collect", "collect/page", "favorite" },
            },
        };

        private static readonly string ReportPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-login-status.json");

        private static readonly string CaptureJsonPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-captured-notes.json");

        private static readonly string CaptureMdPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-captured-notes.md");

        private static readonly string CaptureRawPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-captured-raw.txt");

        private static readonly string CaptureStatsPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-collect-stats.txt");

        // 壳自己的会话状态：上次在看哪个平台、各平台上次的收藏页地址。
        // 目的很实际：小红书收藏页地址带 uid，构造不出来，重启后靠它一步回到收藏列表，
        // 避免"点开壳发现页面根本不在收藏页"这种看起来像抓取失败的情况。
        private static readonly string SessionStatePath =
            Path.Combine(Path.GetTempPath(), "wb-shell-session-state.json");

        // --extract：每条笔记一行 JSONL（原文 + 结构体检），外加一份统计。
        private static readonly string ExtractOutPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-extracted-notes.jsonl");

        private static readonly string ExtractStatsPath =
            Path.Combine(Path.GetTempPath(), "wb-shell-extract-stats.txt");

        // 取正文探针：只读取页面自带的 __INITIAL_STATE__，自己不构造任何请求、不碰签名。
        // 这一版是"探索式"的——先回答「正文到底在哪个字段、风控信号是什么」，
        // 而不是硬编码一条路径然后赌它对。跑完看 wb-shell-extracted-notes.jsonl 的 descHits。
        private const string ExtractScript = @"
(function () {
  try {
    var out = { url: location.href, docTitle: document.title, ts: new Date().toISOString() };
    var s = window.__INITIAL_STATE__;
    out.hasState = !!(s && typeof s === 'object');
    out.stateType = typeof s;
    if (out.hasState) {
      out.noteKeys = s.note ? Object.keys(s.note).slice(0, 20) : null;
      // 第一版从根节点遍历，结果被 global/user 里的无关字段塞满 12 个坑，
      // note 排在后面根本没轮到。这版只深挖 .note 子树。
      var hits = [];
      function walk(node, path, depth) {
        if (depth > 8 || hits.length >= 12) { return; }
        if (!node || typeof node !== 'object') { return; }
        if (Array.isArray(node)) {
          if (node.length > 0) { walk(node[0], path + '[0]', depth + 1); }
          return;
        }
        var keys = Object.keys(node), i, k, v;
        for (i = 0; i < keys.length; i++) {
          k = keys[i]; v = node[k];
          if (typeof v === 'string' && (k === 'desc' || k === 'content' || k === 'text') && v.length > 0) {
            hits.push({ p: path + '.' + k, len: v.length, head: v.slice(0, 80) });
            if (hits.length >= 12) { return; }
          }
        }
        for (i = 0; i < keys.length && hits.length < 12; i++) {
          walk(node[keys[i]], path + '.' + keys[i], depth + 1);
        }
      }
      if (s.note) { walk(s.note, '.note', 0); }
      out.noteHits = hits;
      // 直奔 note.noteDetailMap.<id>.note.desc —— 已知这是小红书正文所在的路径
      var dm = s.note && s.note.noteDetailMap ? s.note.noteDetailMap : null;
      var k0 = dm ? Object.keys(dm)[0] : null;
      out.firstDetailKey = k0;
      if (k0) {
        var nd = dm[k0].note;
        if (nd) {
          out.noteId = nd.noteId || k0;
          out.title = nd.title || null;
          out.type = nd.type || null;
          out.time = nd.time || null;
          out.lastUpdateTime = nd.lastUpdateTime || null;
          out.ipLocation = nd.ipLocation || null;
          out.desc = nd.desc || '';
          out.descLen = out.desc.length;
          if (nd.user) {
            out.author = { userId: nd.user.userId || null, nickName: nd.user.nickName || null,
                           avatar: nd.user.avatar || null };
          }
          if (nd.interactInfo) {
            out.interact = { liked: String(nd.interactInfo.likedCount || '0'),
                             collected: String(nd.interactInfo.collectedCount || '0'),
                             comments: String(nd.interactInfo.commentCount || '0'),
                             shared: String(nd.interactInfo.shareCount || '0') };
          }
          if (nd.tagList && nd.tagList.length) {
            out.tags = nd.tagList.map(function (t) { return t.name; }).slice(0, 20);
          }
          if (nd.imageList && nd.imageList.length) {
            out.imageCount = nd.imageList.length;
            out.images = nd.imageList.map(function (im) {
              var u = im.url_default || im.urlDefault
                   || (im.info_list && im.info_list.length ? im.info_list[0].url : null);
              return { url: u, w: im.width || null, h: im.height || null };
            }).slice(0, 20);
          }
        }
        var cs = dm[k0].comments;
        if (cs && cs.list && cs.list.length) {
          out.commentCount = cs.list.length;
          out.comments = cs.list.slice(0, 10).map(function (c) {
            return { user: (c.user && c.user.nickName) || null, content: c.content || '',
                     likes: String((c.interactInfo && c.interactInfo.likedCount) || '0') };
          });
        }
      }
    }
    // 另一条路：直接从 DOM 取正文，不猜路径
    var d = document.querySelector('#detail-desc')
         || document.querySelector('.desc')
         || document.querySelector('#noteContainer');
    out.domSelector = d ? (d.id ? ('#' + d.id) : String(d.className).slice(0, 40)) : null;
    var dt = d ? (d.innerText || '') : '';
    out.domLen = dt.length;
    out.domHead = dt.slice(0, 120);
    var b = document.body ? document.body.innerText : '';
    out.bodyLen = b.length;
    // 风控判据：不要对 body 全文做正则。
    // 教训（09-22 实测）：一条讲 Agent 求职的视频笔记被误判 riskCaptcha=true ——
    //   它的正文只有 106 字（全是话题标签）、评论 10 条全正常、图片/互动数据齐全，
    //   页面完全没被拦；命中是因为右侧「推荐 feed」里出现了同类的技术干货标题，
    //   而 body.innerText 把推荐流也算进去了。
    // 修法两条，缺一不可：
    //   ① 数据到手就不算被拦 —— 我们的目的是取正文，正文拿不到才谈得上风控；
    //   ② 只在页面【前 600 字】里找 —— 整页遮罩式的验证码/登录墙文案必然在开头，
    //      而推荐流、评论区都在下方，天然被排除。
    var gotData = !!(out.hasState && out.descLen > 0);
    out.rawRiskCaptcha = /验证码|滑块|安全验证|操作频繁|访问异常/.test(b);
    out.rawRiskLoginWall = /登录后查看|登录以查看|登录查看更多|登录后才可以/.test(b);
    out.riskCaptcha = !gotData
        && /验证码|滑块|安全验证|操作频繁|访问异常/.test(b.slice(0, 600));
    out.riskLoginWall = !gotData
        && /登录后查看|登录以查看|登录查看更多|登录后才可以/.test(b.slice(0, 600));
    out.hasNoteContainer = !!document.querySelector('#noteContainer, .note-container, .note-content');
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ error: String(e), url: location.href });
  }
})()";

        // 滚动探针：自己不滚动，只回答"页面到底动了多少"。
        // 教训（09-20 实测）：对 overflow:visible 的元素赋值 scrollTop 会被内核直接忽略，
        // 上一版按 scrollHeight 最大的元素去挑，挑到的正是这种伪容器，所以 top 恒为 0。
        // 这里只认 overflow-y ∈ auto/scroll/overlay 的真容器，并把页面位移一并取回。
        private const string ScrollProbeScript = @"
(function () {
  try {
    var out = {
      url: String(location.href).slice(0, 160),
      windowY: Math.round(window.pageYOffset || document.documentElement.scrollTop || 0),
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
      candidates: 0,
      bestTop: 0,
      bestRoom: 0,
      bestTag: '(none)',
      docHeight: Math.round((document.scrollingElement || document.documentElement).scrollHeight || 0),
      atBottom: false
    };
    var nodes = document.querySelectorAll('div,main,section,ul,ol');
    var bestRoom = 0;
    for (var i = 0; i < nodes.length; i++) {
      var d = nodes[i];
      var oy = '';
      try { oy = window.getComputedStyle(d).overflowY; } catch (e) { oy = ''; }
      if (oy !== 'auto' && oy !== 'scroll' && oy !== 'overlay') { continue; }
      var room = d.scrollHeight - d.clientHeight;
      if (room < 100 || d.clientHeight < 120) { continue; }
      out.candidates++;
      if (room > bestRoom) {
        bestRoom = room;
        out.bestRoom = room;
        out.bestTop = Math.round(d.scrollTop);
        var cls = (d.className && d.className.toString) ? d.className.toString() : '';
        out.bestTag = d.tagName + (cls ? '.' + cls.split(' ')[0] : '');
      }
    }
    out.atBottom = (out.windowY + out.viewportH) >= (out.docHeight - 90);
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ error: '' + e }); }
})();
";

        // 兜底推法：滚轮推不动时，只对 overflow 合规的真容器赋值 scrollTop；
        // 找不到真容器才退回 window.scrollBy。绝不碰 overflow:visible 的元素。
        private static string BuildForceScrollScript(int step)
        {
            return @"
(function () {
  try {
    var step = " + step.ToString(System.Globalization.CultureInfo.InvariantCulture) + @";
    var nodes = document.querySelectorAll('div,main,section,ul,ol');
    var best = null, bestRoom = 0;
    for (var i = 0; i < nodes.length; i++) {
      var d = nodes[i];
      var oy = '';
      try { oy = window.getComputedStyle(d).overflowY; } catch (e) { oy = ''; }
      if (oy !== 'auto' && oy !== 'scroll' && oy !== 'overlay') { continue; }
      var room = d.scrollHeight - d.clientHeight;
      if (room < 100 || d.clientHeight < 120) { continue; }
      if (room > bestRoom) { bestRoom = room; best = d; }
    }
    if (best) {
      best.scrollTop = best.scrollTop + step;
      return 'container=' + Math.round(best.scrollTop) + '/' + best.scrollHeight;
    }
    window.scrollBy(0, step);
    return 'window=' + Math.round(window.pageYOffset);
  } catch (e) { return 'err:' + e; }
})();
";
        }

        // 只在诊断时用：把页面的「tab / 数字角标」结构**原样 dump** 出来。
        // 旧版只挑「纯数字叶子」，结果扫到的全是粉丝数/获赞数，tab 上的「笔记·423」一条没抓到
        // （tab 文本多半是「文字+数字」同处一个元素，或数字节点带子元素，被判为非叶子）。
        // 现在改成结构自描述：连标签名/class/角标/「加载中」的祖先链一起记，回来肉眼就能判断口径。
        private const string DomNumbersScript = @"
(function () {
  try {
    var out = {
      href: '', title: '', noteIds: 0, scanned: 0,
      tabs: [], wordNums: [], counts: [], numbers: [],
      loadAncestor: '', bodyTail: ''
    };
    out.href = String(location.href).slice(0, 170);
    out.title = String(document.title).slice(0, 90);

    function tag(el) {
      var c = '';
      try { c = (el.className && el.className.toString) ? el.className.toString() : ''; } catch (e) { }
      return el.tagName + (el.id ? '#' + el.id : '') + (c ? '.' + c.split(' ').slice(0, 2).join('.') : '');
    }
    function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }

    var i, n, t, k;

    // 1) 标准 tab / tab 类容器：结构上最可能挂总数的地方
    var tabish = document.querySelectorAll('[role=""tab""],[role=""tablist""],[class*=""tab-item""],[class*=""tabbar""],[class*=""tab-bar""],[class*=""tabList""]');
    for (i = 0; i < tabish.length && out.tabs.length < 30; i++) {
      t = norm(tabish[i].textContent);
      if (t && t.length <= 30) { out.tabs.push(tag(tabish[i]) + ' >> ' + t); }
    }

    // 2) 「文字 + 数字」短标签：笔记·423 / 专辑·1 这类，连标签结构一起记
    var all = document.querySelectorAll('div,span,em,strong,i,a,li,button,h1,h2,h3,h4,dt,dd');
    var seen = {};
    for (i = 0; i < all.length && i < 20000; i++) {
      n = all[i];
      out.scanned = i;
      t = norm(n.textContent);
      if (!t || t.length > 24) { continue; }
      if (/^(笔记|专辑|文件|收藏|赞过|作品|发布|喜欢|观看|动态|全部|视频|图文)\s*[·•・:：]?\s*\d{0,6}$/.test(t)) {
        k = tag(n) + ' >> ' + t;
        if (!seen[k]) { seen[k] = 1; if (out.wordNums.length < 30) { out.wordNums.push(k); } }
      }
      if (!seen['n' + t] && /^\d{1,7}$/.test(t) && n.children.length <= 3) {
        seen['n' + t] = 1;
        if (out.numbers.length < 40) { out.numbers.push(tag(n) + '=' + t); }
      }
    }

    // 3) 所有 class 含 count / num 的角标
    var cn = document.querySelectorAll('[class*=""count""],[class*=""num""]');
    for (i = 0; i < cn.length && out.counts.length < 30; i++) {
      t = norm(cn[i].textContent);
      if (t && t.length <= 12) { out.counts.push(tag(cn[i]) + '=' + t); }
    }

    // 4) DOM 里真实出现的笔记链接数（去重）——用来和「已抓条目数」对齐
    var ids = {};
    var as = document.querySelectorAll('a[href]');
    for (i = 0; i < as.length; i++) {
      var m = String(as[i].getAttribute('href')).match(/(?:explore|discovery\/item)\/([0-9a-fA-F]{24})/);
      if (m) { ids[m[1]] = 1; }
    }
    out.noteIds = Object.keys(ids).length;

    // 5) 人眼看到的页面底部原文（最直白的「有没有更多」）
    out.bodyTail = norm(document.body.innerText).slice(-360);

    // 6) 「加载中」挂在哪个容器里（往上三层）
    var cands = document.querySelectorAll('div,span,p,a,li,section');
    for (i = cands.length - 1; i >= 0 && i > cands.length - 2000; i--) {
      t = norm(cands[i].textContent);
      if (t === '加载中' || t === '加载更多' || t === '正在加载') {
        var chain = [];
        var cur = cands[i];
        for (var d = 0; d < 3 && cur; d++) { chain.push(tag(cur)); cur = cur.parentElement; }
        out.loadAncestor = chain.join(' < ');
        break;
      }
    }
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ error: '' + e }); }
})();
";

        // 只在诊断时用：回答「268 到底是服务端给的、还是页面没渲染出来」。
        // 数 DOM 里真实存在的卡片、页面底部的提示语、以及「已失效」占位卡。
        private const string BottomStateScript = @"
(function () {
  try {
    var out = {
      cards: 0,
      cardsBySelector: '',
      bottomText: '',
      expired: 0,
      docHeight: Math.round(document.documentElement.scrollHeight || 0),
      atBottom: false
    };
    var sels = ['section.note-item', 'div.note-item', 'a.cover', 'a[href*=""/explore/""]', 'a[href*=""xsec_token""]'];
    var bestCount = 0, bestSel = '';
    for (var i = 0; i < sels.length; i++) {
      var n = document.querySelectorAll(sels[i]).length;
      if (n > bestCount) { bestCount = n; bestSel = sels[i]; }
    }
    out.cards = bestCount;
    out.cardsBySelector = bestSel;

    out.expired = document.querySelectorAll('[class*=""expired""], [class*=""invalid""], [class*=""deleted""]').length;

    var tail = '';
    var all = document.querySelectorAll('div,span,p');
    for (var j = all.length - 1; j >= 0 && j > all.length - 400; j--) {
      var t = (all[j].textContent || '').trim();
      if (t.length > 0 && t.length < 30 && /没有更多|到底|暂无|已显示全部|加载中|上拉/.test(t)) {
        tail = t;
        break;
      }
    }
    out.bottomText = tail;

    var y = Math.round(window.pageYOffset || document.documentElement.scrollTop || 0);
    out.atBottom = (y + window.innerHeight) >= (out.docHeight - 80);
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ error: '' + e }); }
})();
";

        // 在页面上下文里注入：只被动接住页面自己发出的"列表类"响应体。
        // 不改请求、不造请求、不碰签名——签名仍由页面自己的 JS 生成。
        private const string HookScript = @"
(function () {
  if (window.__wbHookInstalled) { return; }
  window.__wbHookInstalled = true;
  window.__wbCaptured = [];
  window.__wbPageChain = [];
  window.__wbReqLog = [];
  var KEYS = ['/note/collect/page', '/api/v4/collections', '/collections/', 'fav/resource/list', 'favlist'];

  function match(url) {
    if (!url) { return false; }
    for (var i = 0; i < KEYS.length; i++) {
      if (url.indexOf(KEYS[i]) >= 0) { return true; }
    }
    return false;
  }

  function push(url, text) {
    try {
      if (!text || text.length > 3000000) { return; }
      window.__wbCaptured.push({ url: String(url), body: text });
    } catch (e) { }

    // 顺手把分页元信息单独记一份：请求cursor / 返回cursor / has_more / 本页条数 / 首条 id。
    // 原始 body 落盘时只留前 1200 字符，而 cursor 常排在 notes 之后会被截掉，
    // 光看落盘文件看不清分页链，所以在这里就地解析好。
    try {
      var reqCursor = '';
      var m = String(url).match(/[?&]cursor=([^&]*)/);
      if (m) { reqCursor = m[1]; }

      var j = JSON.parse(text);
      var d = j && (j.data || j.result);
      if (d) {
        var arr = d.notes || d.items || d.list || d.note_list || [];
        if (arr && arr.length) {
          var first = arr[0];
          window.__wbPageChain.push({
            url: String(url).slice(0, 200),
            cursor: reqCursor,
            nextCursor: d.cursor || '',
            hasMore: (typeof d.has_more === 'undefined') ? null : d.has_more,
            count: arr.length,
            firstId: (first && (first.note_id || first.id || first.noteId)) || ''
          });
        }
      }
    } catch (e) { }
  }

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function () {
      var args = arguments;
      var url = null;
      try {
        url = (typeof args[0] === 'string') ? args[0] : (args[0] && args[0].url);
      } catch (e) { }
      try {
        if (match(url)) {
          var fInit = args[1] || {};
          window.__wbReqLog.push({
            kind: 'fetch',
            url: String(url),
            method: fInit.method || 'GET',
            headers: fInit.headers ? JSON.parse(JSON.stringify(fInit.headers)) : null,
            credentials: fInit.credentials || '(default)'
          });
        }
      } catch (e) { }
      var p = origFetch.apply(this, args);
      if (match(url)) {
        try {
          p.then(function (res) {
            try { res.clone().text().then(function (t) { push(url, t); }); } catch (e) { }
          });
        } catch (e) { }
      }
      return p;
    };
  }

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (method, url) {
    try { this.__wbUrl = url; this.__wbMethod = method; this.__wbHdr = {}; } catch (e) { }
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    try { if (this.__wbHdr) { this.__wbHdr[k] = v; } } catch (e) { }
    return origSetHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    try {
      if (match(this.__wbUrl)) {
        window.__wbReqLog.push({
          kind: 'xhr',
          url: String(this.__wbUrl),
          method: this.__wbMethod || '',
          headers: this.__wbHdr ? JSON.parse(JSON.stringify(this.__wbHdr)) : null
        });
      }
    } catch (e) { }
    var self = this;
    try {
      self.addEventListener('load', function () {
        try {
          if (match(self.__wbUrl)) { push(self.__wbUrl, self.responseText); }
        } catch (e) { }
      });
    } catch (e) { }
    return origSend.apply(this, arguments);
  };
})();
";

        private readonly List<CapturedNote> _capturedNotes = new List<CapturedNote>();

        private int _capturedItemCount;

        private int _lastCaptureLength;

        private List<int> _lastPageCounts = new List<int>();

        private string _lastHasMore = "(未读到)";

        private string _lastPageChain = "(未读到)";

        private string _lastScrollInfo;

        private string _lastScrollTrail;

        private int _mouseX = 500;

        private int _mouseY = 400;

        private readonly WebView2 _view = new ProductWebView();
        private readonly Label _status = new Label();
        private readonly Timer _poll = new Timer();

        private readonly Dictionary<string, object> _responses =
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

        private readonly List<CookieSnapshot> _snapshots = new List<CookieSnapshot>();

        private CoreWebView2 _core;
        private string _engineVersion = "(unknown)";
        private string _proxyNote = "none";
        private bool _ready;
        private bool _autoScrolling;
        private int _currentPlatform;

        private readonly ShellSessionState _session = new ShellSessionState();

        private readonly bool _diagnose;

        // 运行序号：用来发现「同一个流程被并发跑了两次」这种隐蔽故障
        // （并发跑第二次会被 _autoScrolling 挡住提前返回，进而 5 秒后关窗）。
        private int _diagnoseRuns;
        private int _autoscrollRuns;
        private readonly ExtractOptions _extract;
        private readonly EvalOptions _eval;
        private readonly bool _silent;
        private readonly bool _productMode;
        private readonly string _productUrl;
        private readonly ProductChromePanel _productChrome = new ProductChromePanel();
        private readonly ProductChromePanel _productChromeButtonPanel = new ProductChromePanel();
        private readonly ProductChromeLabel _productChromeMark = new ProductChromeLabel();
        private readonly ProductChromeLabel _productChromeName = new ProductChromeLabel();
        private readonly ProductChromeLabel _productChromeSubtitle = new ProductChromeLabel();
        private readonly ProductChromeButton _productMinimizeButton = new ProductChromeButton();
        private readonly ProductChromeButton _productMaximizeButton = new ProductChromeButton();
        private readonly ProductChromeButton _productCloseButton = new ProductChromeButton();
        private Rectangle _productRestoreBounds;
        private long _lastProductChromeClickTicks;
        private Point _lastProductChromeClickPosition;
        private bool _productMaximized;
        private CoreWebView2Environment _environment;
        private XhsLoginForm _xhsLoginForm;
        private ZhihuLoginForm _zhihuLoginForm;
        private readonly string _productOrigin;
        private string _pendingLoginRequestId;
        private string _pendingZhihuLoginRequestId;
        private bool _closingProduct;
        private bool _extracting;

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams parameters = base.CreateParams;
                if (_productMode)
                {
                    parameters.Style |= WsThickFrame;
                }

                return parameters;
            }
        }

        public ShellForm(
            bool diagnose,
            ExtractOptions extract = null,
            bool silentWindow = false,
            EvalOptions eval = null,
            bool productMode = false,
            string productUrl = null)
        {
            _diagnose = diagnose;
            _extract = extract;
            _silent = silentWindow;
            _eval = eval;
            _productMode = productMode;
            _productUrl = productUrl ?? "http://127.0.0.1:8765/";
            _productOrigin = new Uri(_productUrl).GetLeftPart(UriPartial.Authority);
            Text = productMode ? "多源内容知识库" : "登录外壳（实验）— 在窗口内登录，凭证不出本机";
            Width = 1180;
            Height = 820;
            StartPosition = FormStartPosition.CenterScreen;
            if (productMode)
            {
                FormBorderStyle = FormBorderStyle.None;
                MinimumSize = new Size(480, 360);
                ((ProductWebView)_view).ResizeHitTest = IsProductResizeBorder;
            }

            _view.Dock = DockStyle.Fill;
            Controls.Add(_view);
            if (productMode)
            {
                BuildProductChrome();
            }
            else
            {
                BuildToolbar();
            }

            if (!productMode)
            {
                _status.Dock = DockStyle.Bottom;
                _status.Height = 28;
                _status.TextAlign = System.Drawing.ContentAlignment.MiddleLeft;
                _status.Padding = new Padding(10, 0, 0, 0);
                _status.Text = "正在启动内嵌浏览器…";
                Controls.Add(_status);
            }

            Load += OnLoaded;
            FormClosing += (sender, args) =>
            {
                if (_productMode)
                {
                    _closingProduct = true;
                    if (_xhsLoginForm != null)
                    {
                        _xhsLoginForm.CloseForShutdown();
                        _xhsLoginForm = null;
                    }
                    if (_zhihuLoginForm != null)
                    {
                        _zhihuLoginForm.CloseForShutdown();
                        _zhihuLoginForm = null;
                    }
                    return;
                }

                try
                {
                    // 关键：CloseReason 能直接回答「谁关的窗口」（用户点X / 任务管理器 / 系统关机）。
                    // 09-21 出现过「诊断跑到第 2 轮窗口就没了、报告也没写」的情况，需要这条来定性。
                    Trace.Log(
                        "form closing: reason=" + args.CloseReason
                        + " diagnoseRuns=" + _diagnoseRuns
                        + " autoscrollRuns=" + _autoscrollRuns
                        + " autoScrolling=" + _autoScrolling);
                    WriteReport("closing");
                }
                catch
                {
                }
            };
        }

        private void BuildToolbar()
        {
            var bar = new FlowLayoutPanel();
            bar.Dock = DockStyle.Top;
            bar.Height = 46;
            bar.Padding = new Padding(8, 8, 8, 4);
            bar.WrapContents = false;
            bar.FlowDirection = FlowDirection.LeftToRight;

            for (int index = 0; index < Targets.Length; index++)
            {
                int captured = index;
                var button = new Button();
                button.Text = Targets[index].Display;
                button.Width = 84;
                button.Height = 28;
                button.Click += (sender, args) => NavigateTo(captured);
                bar.Controls.Add(button);
            }

            var favorites = new Button();
            favorites.Text = "打开我的收藏";
            favorites.Width = 120;
            favorites.Height = 28;
            favorites.Click += async (sender, args) => await OpenFavoritesAsync();
            bar.Controls.Add(favorites);

            var autoScroll = new Button();
            autoScroll.Text = "自动滚动（拟人）";
            autoScroll.Width = 130;
            autoScroll.Height = 28;
            autoScroll.Click += async (sender, args) => await AutoScrollToEndAsync();
            bar.Controls.Add(autoScroll);

            var capture = new Button();
            capture.Text = "抓取本页内容";
            capture.Width = 120;
            capture.Height = 28;
            capture.Click += async (sender, args) => await CaptureAsync();
            bar.Controls.Add(capture);

            var save = new Button();
            save.Text = "刷新状态并写报告";
            save.Width = 140;
            save.Height = 28;
            save.Click += async (sender, args) =>
            {
                await CollectAllAsync();
                WriteReport("manual");
                SetStatus("报告已写入 " + ReportPath);
            };
            bar.Controls.Add(save);

            var hint = new Label();
            hint.AutoSize = true;
            hint.Padding = new Padding(14, 9, 0, 0);
            hint.Text = "步骤：点平台按钮 → 登录 → 「打开我的收藏」→ 点「自动滚动（拟人）」等它跑完，看状态栏「收藏条目」数";
            bar.Controls.Add(hint);

            Controls.Add(bar);
        }

        private void BuildProductChrome()
        {
            _productChrome.Dock = DockStyle.Top;
            _productChrome.Height = ProductChromeHeight;
            _productChrome.BackColor = ProductChromeColor;
            _productChrome.AccessibleName = "窗口标题栏";
            _productChrome.AccessibleRole = AccessibleRole.TitleBar;
            _productChrome.MouseDown += BeginProductWindowDrag;
            _productChrome.SizeChanged += (sender, args) => UpdateProductChromeLayout();
            _productChrome.ResizeHitTest = IsProductResizeBorder;

            _productChromeMark.ResizeHitTest = IsProductResizeBorder;
            _productChromeMark.Text = "M";
            _productChromeMark.Left = 16;
            _productChromeMark.Top = 13;
            _productChromeMark.Size = new Size(22, 22);
            _productChromeMark.BorderStyle = BorderStyle.FixedSingle;
            _productChromeMark.Font = new Font("Segoe UI", 9F, FontStyle.Bold, GraphicsUnit.Point);
            _productChromeMark.ForeColor = ProductChromeText;
            _productChromeMark.TextAlign = ContentAlignment.MiddleCenter;
            _productChromeMark.MouseDown += BeginProductWindowDrag;

            _productChromeName.ResizeHitTest = IsProductResizeBorder;
            _productChromeName.Text = "多源内容知识库";
            _productChromeName.Left = 50;
            _productChromeName.Top = 0;
            _productChromeName.Height = ProductChromeHeight;
            _productChromeName.AutoEllipsis = false;
            _productChromeName.Font = new Font("Segoe UI", 10F, FontStyle.Bold, GraphicsUnit.Point);
            _productChromeName.ForeColor = ProductChromeText;
            _productChromeName.TextAlign = ContentAlignment.MiddleLeft;
            _productChromeName.MouseDown += BeginProductWindowDrag;

            _productChromeSubtitle.ResizeHitTest = IsProductResizeBorder;
            _productChromeSubtitle.Text = "MULTI-SOURCE DESK";
            _productChromeSubtitle.Top = 0;
            _productChromeSubtitle.Height = ProductChromeHeight;
            _productChromeSubtitle.Font = new Font("Segoe UI", 8F, FontStyle.Regular, GraphicsUnit.Point);
            _productChromeSubtitle.ForeColor = Color.FromArgb(226, 201, 180);
            _productChromeSubtitle.TextAlign = ContentAlignment.MiddleLeft;
            _productChromeSubtitle.MouseDown += BeginProductWindowDrag;

            _productChromeButtonPanel.Dock = DockStyle.Right;
            _productChromeButtonPanel.Width = ProductChromeButtonPanelWidth;
            _productChromeButtonPanel.BackColor = ProductChromeColor;
            _productChromeButtonPanel.ResizeHitTest = IsProductResizeBorder;
            _productChromeButtonPanel.SizeChanged += (sender, args) => UpdateProductChromeLayout();
            ConfigureProductChromeButton(
                _productMinimizeButton,
                ProductChromeGlyphMinimize,
                "最小化",
                Color.FromArgb(148, 91, 57));
            ConfigureProductChromeButton(
                _productMaximizeButton,
                ProductChromeGlyphMaximize,
                "最大化",
                Color.FromArgb(148, 91, 57));
            ConfigureProductChromeButton(
                _productCloseButton,
                ProductChromeGlyphClose,
                "关闭",
                Color.FromArgb(190, 55, 43));
            _productMinimizeButton.Click += (sender, args) => WindowState = FormWindowState.Minimized;
            _productMaximizeButton.Click += (sender, args) => ToggleProductMaximize();
            _productCloseButton.Click += (sender, args) => Close();
            _productChromeButtonPanel.Controls.Add(_productMinimizeButton);
            _productChromeButtonPanel.Controls.Add(_productMaximizeButton);
            _productChromeButtonPanel.Controls.Add(_productCloseButton);

            var bottomRule = new ProductChromePanel
            {
                Dock = DockStyle.Bottom,
                Height = 2,
                BackColor = Color.FromArgb(61, 31, 16),
                ResizeHitTest = IsProductResizeBorder,
            };

            _productChrome.Controls.Add(_productChromeButtonPanel);
            _productChrome.Controls.Add(_productChromeMark);
            _productChrome.Controls.Add(_productChromeName);
            _productChrome.Controls.Add(_productChromeSubtitle);
            _productChrome.Controls.Add(bottomRule);
            Controls.Add(_productChrome);
            _productRestoreBounds = Bounds;
            UpdateProductChromeLayout();
        }

        private static void ConfigureProductChromeButton(
            ProductChromeButton button,
            int glyph,
            string accessibleName,
            Color hoverColor)
        {
            button.Glyph = glyph;
            button.Text = string.Empty;
            button.AccessibleName = accessibleName;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 0;
            button.FlatAppearance.MouseOverBackColor = hoverColor;
            button.FlatAppearance.MouseDownBackColor = Color.FromArgb(101, 53, 25);
            button.BackColor = ProductChromeColor;
            button.ForeColor = ProductChromeText;
            button.UseVisualStyleBackColor = false;
            button.TabStop = true;
        }

        private void UpdateProductChromeLayout()
        {
            if (!_productMode || _productChrome.IsDisposed)
            {
                return;
            }

            int chromeHeight = _productChrome.ClientSize.Height;
            _productChromeMark.Top = Math.Max(0, (chromeHeight - _productChromeMark.Height) / 2);
            _productChromeName.Top = 0;
            _productChromeName.Height = chromeHeight;
            _productChromeSubtitle.Top = 0;
            _productChromeSubtitle.Height = chromeHeight;

            int titleAreaRight = _productChrome.ClientSize.Width
                - _productChromeButtonPanel.Width
                - 18;
            int titleAvailableWidth = Math.Max(0, titleAreaRight - _productChromeName.Left);
            Size titleTextSize = TextRenderer.MeasureText(
                _productChromeName.Text,
                _productChromeName.Font,
                Size.Empty,
                TextFormatFlags.SingleLine | TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix);
            int titleSafetyMargin = Math.Max(18, _productChromeName.Font.Height);
            int titleWidth = titleTextSize.Width + titleSafetyMargin;
            _productChromeName.Width = Math.Min(titleAvailableWidth, titleWidth);
            _productChromeName.AutoEllipsis = titleWidth > titleAvailableWidth;

            _productChromeSubtitle.Left = _productChromeName.Right + 14;
            _productChromeSubtitle.Width = Math.Max(0, titleAreaRight - _productChromeSubtitle.Left);
            Size subtitleTextSize = TextRenderer.MeasureText(
                _productChromeSubtitle.Text,
                _productChromeSubtitle.Font,
                Size.Empty,
                TextFormatFlags.SingleLine | TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix);
            _productChromeSubtitle.Visible = _productChrome.ClientSize.Width >= 650
                && _productChromeSubtitle.Width >= subtitleTextSize.Width;

            int buttonPanelWidth = _productChromeButtonPanel.ClientSize.Width;
            int buttonPanelHeight = _productChromeButtonPanel.ClientSize.Height;
            int buttonWidth = Math.Min(
                buttonPanelWidth / 3,
                (int)Math.Round(buttonPanelWidth * (double)ProductChromeButtonWidth / ProductChromeButtonPanelWidth));
            int buttonInset = Math.Max(
                4,
                (int)Math.Round(buttonPanelHeight * (double)ProductResizeBorderLogicalPixels / ProductChromeHeight));
            int buttonHeight = Math.Max(0, buttonPanelHeight - buttonInset * 2);
            int buttonTop = Math.Max(0, (buttonPanelHeight - buttonHeight) / 2);
            _productMinimizeButton.SetBounds(0, buttonTop, buttonWidth, buttonHeight);
            _productMaximizeButton.SetBounds(buttonWidth, buttonTop, buttonWidth, buttonHeight);
            _productCloseButton.SetBounds(buttonWidth * 2, buttonTop, buttonWidth, buttonHeight);
            UpdateProductMaximizeButton();
        }

        private void BeginProductWindowDrag(object sender, MouseEventArgs args)
        {
            if (!_productMode || args.Button != MouseButtons.Left)
            {
                return;
            }

            if (IsProductChromeDoubleClick(Cursor.Position))
            {
                ToggleProductMaximize();
                return;
            }

            if (_productMaximized)
            {
                RestoreProductWindowForDrag();
            }

            ReleaseCapture();
            SendMessage(Handle, WmNcLButtonDown, (IntPtr)HtCaption, IntPtr.Zero);
        }

        private bool IsProductChromeDoubleClick(Point position)
        {
            long now = Environment.TickCount64;
            Size clickArea = SystemInformation.DoubleClickSize;
            bool isDoubleClick = _lastProductChromeClickTicks > 0
                && now - _lastProductChromeClickTicks <= SystemInformation.DoubleClickTime
                && Math.Abs(position.X - _lastProductChromeClickPosition.X) <= clickArea.Width
                && Math.Abs(position.Y - _lastProductChromeClickPosition.Y) <= clickArea.Height;
            _lastProductChromeClickTicks = isDoubleClick ? 0 : now;
            _lastProductChromeClickPosition = position;
            return isDoubleClick;
        }

        private void RestoreProductWindowForDrag()
        {
            Point cursor = Cursor.Position;
            double horizontalRatio = Width <= 0 ? 0.5 : (double)(cursor.X - Left) / Width;
            horizontalRatio = Math.Max(0, Math.Min(1, horizontalRatio));
            int titleOffset = Math.Max(0, Math.Min(ProductChromeHeight / 2, cursor.Y - Top));

            _productMaximized = false;
            Bounds = _productRestoreBounds;
            Location = new Point(
                cursor.X - (int)Math.Round(Width * horizontalRatio),
                cursor.Y - titleOffset);
            UpdateProductMaximizeButton();
        }

        private void ToggleProductMaximize()
        {
            if (_productMaximized)
            {
                _productMaximized = false;
                Bounds = _productRestoreBounds;
            }
            else
            {
                _productRestoreBounds = Bounds;
                _productMaximized = true;
                Bounds = Screen.FromHandle(Handle).WorkingArea;
            }

            UpdateProductMaximizeButton();
        }

        private void UpdateProductMaximizeButton()
        {
            if (_productMaximizeButton.IsDisposed)
            {
                return;
            }

            _productMaximizeButton.Glyph = _productMaximized
                ? ProductChromeGlyphRestore
                : ProductChromeGlyphMaximize;
            _productMaximizeButton.AccessibleName = _productMaximized ? "还原窗口" : "最大化";
            _productMaximizeButton.Invalidate();
        }

        private bool IsProductResizeBorder(Point screenPoint)
        {
            if (!_productMode || _productMaximized || WindowState != FormWindowState.Normal)
            {
                return false;
            }

            return GetProductResizeHitTest(PointToClient(screenPoint)) != HtClient;
        }

        private int GetProductResizeHitTest(Point clientPoint)
        {
            int border = Math.Max(
                4,
                (int)Math.Round(ProductResizeBorderLogicalPixels * DeviceDpi / 96.0));
            bool left = clientPoint.X >= 0 && clientPoint.X < border;
            bool right = clientPoint.X < ClientSize.Width
                && clientPoint.X >= ClientSize.Width - border;
            bool top = clientPoint.Y >= 0 && clientPoint.Y < border;
            bool bottom = clientPoint.Y < ClientSize.Height
                && clientPoint.Y >= ClientSize.Height - border;

            if (top && left)
            {
                return HtTopLeft;
            }
            if (top && right)
            {
                return HtTopRight;
            }
            if (bottom && left)
            {
                return HtBottomLeft;
            }
            if (bottom && right)
            {
                return HtBottomRight;
            }
            if (left)
            {
                return HtLeft;
            }
            if (right)
            {
                return HtRight;
            }
            if (top)
            {
                return HtTop;
            }
            if (bottom)
            {
                return HtBottom;
            }

            return HtClient;
        }

        private static Point ScreenPointFromMessage(Message message)
        {
            long point = message.LParam.ToInt64();
            return new Point(
                unchecked((short)(point & 0xffff)),
                unchecked((short)((point >> 16) & 0xffff)));
        }

        protected override void WndProc(ref Message message)
        {
            if (_productMode && message.Msg == WmNcHitTest)
            {
                base.WndProc(ref message);
                if (!_productMaximized && WindowState == FormWindowState.Normal
                    && (int)message.Result == HtClient)
                {
                    int hitTest = GetProductResizeHitTest(
                        PointToClient(ScreenPointFromMessage(message)));
                    if (hitTest != HtClient)
                    {
                        message.Result = (IntPtr)hitTest;
                    }
                }

                return;
            }

            base.WndProc(ref message);
        }

        private async void OnLoaded(object sender, EventArgs args)
        {
            try
            {
                string userData = GetShellUserDataDirectory();
                Directory.CreateDirectory(userData);

                string proxy = ResolveProxy();
                if (string.IsNullOrWhiteSpace(proxy))
                {
                    proxy = null;
                }

                // 本机跑通需要 --disable-gpu；--no-sandbox 仅本机实验用，产品化不得默认携带。
                string browserArguments = _productMode
                    ? "--disable-gpu"
                    : "--disable-gpu --no-sandbox";
                if (!string.IsNullOrWhiteSpace(proxy))
                {
                    // Chromium 不读 HTTP(S)_PROXY 环境变量，必须显式传给引擎。
                    browserArguments += " --proxy-server=" + proxy;
                    _proxyNote = proxy;
                }

                var options = new CoreWebView2EnvironmentOptions();
                options.AdditionalBrowserArguments = browserArguments;

                CoreWebView2Environment environment =
                    await CoreWebView2Environment.CreateAsync(null, userData, options);
                _environment = environment;
                await _view.EnsureCoreWebView2Async(environment);

                _core = _view.CoreWebView2;
                _engineVersion = _core.Environment.BrowserVersionString;
                if (_productMode)
                {
                    _core.WebMessageReceived += OnProductMessageReceived;
                    _ready = true;
                    _core.Navigate(_productUrl);
                    return;
                }

                _core.WebResourceResponseReceived += OnResponseReceived;
                _core.SourceChanged += (sender2, args2) =>
                {
                    RememberFavoriteUrl();
                    UpdateStatusLabel();
                };
                await _core.AddScriptToExecuteOnDocumentCreatedAsync(HookScript);
                Trace.Log("hook installed");

                _ready = true;
                Trace.Log("ready: engine=" + _engineVersion + " args=" + browserArguments);

                _poll.Interval = 5000;
                _poll.Tick += async (sender2, args2) =>
                {
                    if (_autoScrolling || _extracting)
                    {
                        return;
                    }

                    await CollectAllAsync();
                    await CaptureAsync(silent: true);
                };
                _poll.Start();

                LoadSessionState();
                int startIndex = 0;
                for (int index = 0; index < Targets.Length; index++)
                {
                    if (string.Equals(Targets[index].Name, _session.Platform, StringComparison.OrdinalIgnoreCase))
                    {
                        startIndex = index;
                        break;
                    }
                }

                Trace.Log("start platform=" + Targets[startIndex].Name);
                NavigateTo(startIndex);

                await CollectAllAsync();
                SetStatus(
                    "就绪。当前平台：" + Targets[startIndex].Display
                    + " · 请先「打开我的收藏」再点「自动滚动（拟人）」");

                // 由脚本/WMI 拉起的 GUI 没有前台窗口权限，窗口常常躲在其他窗口后面，
                // 用户会以为"没启动"。启动后短暂置顶抢一次焦点，几秒后自动取消，不长期霸屏。
                if (_silent)
                {
                    ShowInTaskbar = false;
                    WindowState = FormWindowState.Minimized;
                    Trace.Log("window: silent minimized, handle=" + Handle.ToString());
                }
                else
                {
                    TopMost = true;
                    Activate();
                    var unTop = new Timer();
                    unTop.Interval = 4000;
                    unTop.Tick += (sender3, args3) =>
                    {
                        unTop.Stop();
                        unTop.Dispose();
                        TopMost = false;
                        Trace.Log("window: topmost released");
                    };
                    unTop.Start();
                    Trace.Log("window: topmost raised, handle=" + Handle.ToString());
                }

                if (_eval != null)
                {
                    await RunEvalAsync();
                }
                else if (_extract != null)
                {
                    await RunExtractAsync();
                }
                else if (_diagnose)
                {
                    await RunDiagnoseAsync();
                }
            }
            catch (Exception ex)
            {
                Trace.Log("init failed " + ex);
                SetStatus("启动失败：" + ex.Message);
                MessageBox.Show(
                    "内嵌浏览器启动失败：\r\n\r\n" + ex.Message
                    + (_productMode
                        ? string.Empty
                        : "\r\n\r\n详细信息见：\r\n"
                            + Path.Combine(Path.GetTempPath(), "wb-shell-login.trace.txt")),
                    "登录外壳启动失败",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }

        private static string GetShellUserDataDirectory()
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "wb-shell-login-userdata");
        }

        private async void OnProductMessageReceived(
            object sender,
            CoreWebView2WebMessageReceivedEventArgs args)
        {
            if (!_productMode || !IsProductOrigin(args.Source))
            {
                return;
            }

            string requestId = null;
            string requestPlatform = null;
            string xhsOperationId = null;
            try
            {
                using (JsonDocument document = JsonDocument.Parse(args.WebMessageAsJson))
                {
                    JsonElement message = document.RootElement;
                    string platform = message.GetProperty("platform").GetString();
                    requestPlatform = platform;
                    string action = message.GetProperty("action").GetString();
                    requestId = message.GetProperty("requestId").GetString();
                    string scanRequestId = message.TryGetProperty("scanRequestId", out JsonElement scanRequestValue)
                        ? scanRequestValue.GetString() : null;
                    string scanScope = message.TryGetProperty("scope", out JsonElement scanScopeValue)
                        ? scanScopeValue.GetString() : "notes";
                    string albumId = message.TryGetProperty("albumId", out JsonElement albumIdValue)
                        ? albumIdValue.GetString() : null;
                    if (platform == "zhihu"
                        && !string.IsNullOrWhiteSpace(requestId)
                        && requestId.Length <= 100)
                    {
                        if (action != "open_login" && action != "check_session"
                            && action != "disconnect_session" && action != "scan_favorites"
                            && action != "read_content")
                        {
                            return;
                        }
                        if (!string.IsNullOrEmpty(_pendingLoginRequestId)
                            || !string.IsNullOrEmpty(_pendingZhihuLoginRequestId))
                        {
                            SendZhihuMessage(requestId, new ZhihuOperationResult
                            {
                                Status = "REAUTH_REQUIRED",
                                Message = "请先关闭当前平台登录窗口",
                            });
                            return;
                        }

                        ZhihuLoginForm zhihu = await EnsureZhihuLoginFormAsync();
                        if (action == "open_login")
                        {
                            await zhihu.OpenLoginPageAsync();
                            _pendingZhihuLoginRequestId = requestId;
                            zhihu.Show(this);
                            zhihu.BringToFront();
                            return;
                        }
                        ZhihuOperationResult zhihuResult;
                        if (action == "check_session")
                        {
                            zhihuResult = await zhihu.CheckSessionAsync();
                        }
                        else if (action == "disconnect_session")
                        {
                            zhihuResult = await zhihu.ClearCookiesAndVerifyAsync();
                        }
                        else
                        {
                            string url = message.TryGetProperty("url", out JsonElement urlValue)
                                ? urlValue.GetString()
                                : null;
                            zhihuResult = action == "scan_favorites"
                                ? await zhihu.ScanFavoritesAsync(url)
                                : await zhihu.ReadContentAsync(url);
                        }
                        SendZhihuMessage(requestId, zhihuResult);
                        return;
                    }
                    if (platform != "xiaohongshu"
                        || string.IsNullOrWhiteSpace(requestId)
                        || Trace.XhsId(requestId) == "-")
                    {
                        return;
                    }

                    if (action == "trace_favorites")
                    {
                        if (Trace.IsXhsOperationId(requestId)) TraceXhsFrontend(requestId, message);
                        return;
                    }
                    string operation = message.TryGetProperty("operationId", out JsonElement operationValue)
                        ? operationValue.GetString() : null;
                    xhsOperationId = action == "scan_favorites" ? Trace.XhsId(requestId)
                        : Trace.IsXhsOperationId(operation) ? operation : Trace.XhsId(requestId);

                    if (action != "open_login" && action != "check_session" && action != "disconnect_session"
                        && action != "scan_favorites" && action != "cancel_favorites" && action != "read_note")
                    {
                        return;
                    }

                    if (!string.IsNullOrEmpty(_pendingLoginRequestId)
                        || !string.IsNullOrEmpty(_pendingZhihuLoginRequestId))
                    {
                        SendProductMessage(
                            requestId,
                            new XhsSessionResult("REAUTH_REQUIRED", "请先关闭小红书登录窗口后再执行其他操作"));
                        return;
                    }

                    XhsLoginForm login = await EnsureXhsLoginFormAsync();
                    if (action == "cancel_favorites")
                    {
                        login.CancelFavoritesScan(scanRequestId);
                        return;
                    }
                    if (action == "open_login")
                    {
                        _pendingLoginRequestId = requestId;
                        ShowXhsWindow(login);
                        return;
                    }

                    XhsSessionResult result;
                    var started = System.Diagnostics.Stopwatch.StartNew();
                    if (action == "check_session")
                    {
                        result = await login.CheckSessionAsync();
                    }
                    else if (action == "scan_favorites")
                    {
                        ShowXhsWindow(login);
                        result = await login.ScanFavoritesAsync(requestId, scanScope, albumId);
                    }
                    else if (action == "disconnect_session")
                    {
                        result = await login.ClearCookiesAndVerifyAsync();
                    }
                    else if (action == "read_note")
                    {
                        string noteUrl = message.TryGetProperty("url", out JsonElement noteUrlValue)
                            ? noteUrlValue.GetString() : null;
                        string noteScope = message.TryGetProperty("scope", out JsonElement noteScopeValue)
                            ? noteScopeValue.GetString() : null;
                        string noteAlbumId = message.TryGetProperty("albumId", out JsonElement noteAlbumIdValue)
                            ? noteAlbumIdValue.GetString() : null;
                        result = await login.ReadNoteAsync(xhsOperationId, noteUrl, noteScope, noteAlbumId);
                    }
                    else
                    {
                        return;
                    }

                    if (action == "scan_favorites" || action == "read_note")
                    {
                        string layer = action == "scan_favorites" ? "scan" : "note";
                        Trace.LogAlways("xhs-" + layer + " op=" + xhsOperationId + " event=end status="
                            + result.Status + " candidates=" + (result.Candidates?.Count ?? 0)
                            + " albums=" + (result.Albums?.Count ?? 0) + " ms=" + started.ElapsedMilliseconds
                            + " reason=" + result.Message);
                    }
                    SendProductMessage(requestId, result);
                }
            }
            catch (Exception error)
            {
                // 兜底分支原来只回一句「检查失败」，看不出抛出的是什么；先落一行可诊断的日志。
                Trace.LogAlways(
                    "platform-fail platform=" + Trace.XhsId(requestPlatform) + " op=" + (xhsOperationId ?? "-")
                    + " error=" + error.GetType().Name);
                if (!string.IsNullOrWhiteSpace(requestId))
                {
                    if (requestPlatform == "zhihu")
                    {
                        SendZhihuMessage(requestId, new ZhihuOperationResult
                        {
                            Status = "REAUTH_REQUIRED",
                            Message = "知乎登录状态检查失败，请重试",
                        });
                    }
                    else
                    {
                        SendProductMessage(
                            requestId,
                            new XhsSessionResult("REAUTH_REQUIRED", "小红书登录状态检查失败，请重试"));
                    }
                }
            }
        }

        private static void TraceXhsFrontend(string operationId, JsonElement message)
        {
            if (!message.TryGetProperty("event", out JsonElement value)) return;
            string name = value.GetString();
            switch (name)
            {
                case "scan_start": case "scan_timeout": case "scan_complete": case "scan_partial": case "scan_failed":
                case "import_start": case "import_end": case "read_failed":
                case "restore_complete": case "restore_failed": case "created": case "reused": case "import_failed":
                    break;
                default: return;
            }
            var fields = new StringBuilder();
            foreach (string key in new[] { "count", "created", "reused", "shellFailed", "importFailed", "ms" })
            {
                if (message.TryGetProperty(key, out JsonElement number)
                    && number.ValueKind == JsonValueKind.Number && number.TryGetInt32(out int amount))
                    fields.Append(" ").Append(key).Append("=").Append(amount);
            }
            foreach (string key in new[] { "noteId", "jobId" })
            {
                if (message.TryGetProperty(key, out JsonElement id) && id.ValueKind == JsonValueKind.String)
                    fields.Append(" ").Append(key).Append("=").Append(Trace.XhsId(id.GetString()));
            }
            Trace.LogAlways("xhs-ui op=" + operationId + " event=" + name + fields);
        }

        private bool IsProductOrigin(string source)
        {
            Uri uri;
            return Uri.TryCreate(source, UriKind.Absolute, out uri)
                && string.Equals(
                    uri.GetLeftPart(UriPartial.Authority),
                    _productOrigin,
                    StringComparison.OrdinalIgnoreCase);
        }

        private async Task<XhsLoginForm> EnsureXhsLoginFormAsync()
        {
            if (_environment == null || _closingProduct)
            {
                throw new InvalidOperationException("产品壳尚未就绪");
            }

            if (_xhsLoginForm == null || _xhsLoginForm.IsDisposed)
            {
                _xhsLoginForm = new XhsLoginForm(_environment, GetShellUserDataDirectory());
                _xhsLoginForm.UserRequestedClose += OnXhsLoginUserRequestedClose;
                _xhsLoginForm.FavoriteScanProgress += (id, items) => SendProductMessage(
                    id,
                    new XhsSessionResult("PARTIAL", "小红书收藏读取中", null, false, items, null, true));
            }

            await _xhsLoginForm.InitializeAsync();
            return _xhsLoginForm;
        }

        // Show(owner) 对已可见窗体会抛 InvalidOperationException；可见时只激活，不重复 Show。
        private void ShowXhsWindow(XhsLoginForm login)
        {
            if (login.Visible)
            {
                login.Activate();
            }
            else
            {
                login.Show(this);
            }
            login.BringToFront();
        }

        private async Task<ZhihuLoginForm> EnsureZhihuLoginFormAsync()
        {
            if (_environment == null || _closingProduct)
            {
                throw new InvalidOperationException("产品壳尚未就绪");
            }

            if (_zhihuLoginForm == null || _zhihuLoginForm.IsDisposed)
            {
                _zhihuLoginForm = new ZhihuLoginForm(_environment, "知乎 WebView2 会话");
                _zhihuLoginForm.UserRequestedClose += OnZhihuLoginUserRequestedClose;
            }

            await _zhihuLoginForm.InitializeAsync();
            return _zhihuLoginForm;
        }

        private async void OnZhihuLoginUserRequestedClose(object sender, EventArgs args)
        {
            string requestId = _pendingZhihuLoginRequestId;
            _pendingZhihuLoginRequestId = null;
            if (string.IsNullOrEmpty(requestId) || _closingProduct)
            {
                return;
            }

            try
            {
                SendZhihuMessage(requestId, await _zhihuLoginForm.CheckSessionAsync());
            }
            catch
            {
                SendZhihuMessage(requestId, new ZhihuOperationResult
                {
                    Status = "REAUTH_REQUIRED",
                    Message = "知乎登录状态检查失败，请重试",
                });
            }
        }

        private void SendZhihuMessage(string requestId, ZhihuOperationResult result)
        {
            if (_core == null || _closingProduct || string.IsNullOrEmpty(requestId))
            {
                return;
            }

            _core.PostWebMessageAsJson(JsonSerializer.Serialize(new
            {
                type = "platform-session-result",
                requestId,
                platform = "zhihu",
                status = result.Status,
                message = result.Message,
                browser_profile = result.BrowserProfile,
                session_invalidated = result.SessionInvalidated,
                candidates = result.Candidates?.Select(item => new
                {
                    candidate_id = item.CandidateId,
                    title = item.Title,
                    author = item.Author,
                    url = item.Url,
                    source_type = item.SourceType,
                }).ToList(),
                content = result.Content == null ? null : new
                {
                    title = result.Content.Title,
                    author = result.Content.Author,
                    text = result.Content.Text,
                },
            }));
        }

        private async void OnXhsLoginUserRequestedClose(object sender, EventArgs args)
        {
            string requestId = _pendingLoginRequestId;
            _pendingLoginRequestId = null;
            if (string.IsNullOrEmpty(requestId) || _closingProduct)
            {
                return;
            }

            try
            {
                XhsSessionResult result = await _xhsLoginForm.CheckSessionAsync();
                SendProductMessage(requestId, result);
            }
            catch
            {
                SendProductMessage(
                    requestId,
                    new XhsSessionResult("REAUTH_REQUIRED", "小红书登录状态检查失败，请重试"));
            }
        }

        private void SendProductMessage(string requestId, XhsSessionResult result)
        {
            if (_core == null || _closingProduct || string.IsNullOrEmpty(requestId))
            {
                return;
            }

            _core.PostWebMessageAsJson(JsonSerializer.Serialize(new
            {
                type = "platform-session-result",
                requestId,
                platform = "xiaohongshu",
                status = result.Status,
                message = result.Message,
                browser_profile = result.BrowserProfile,
                session_invalidated = result.SessionInvalidated,
                progress = result.Progress,
                candidates = result.Candidates?.Select(item => new
                {
                    candidate_id = item.CandidateId,
                    id = item.Id,
                    title = item.Title,
                    author = item.Author,
                    type = item.Type,
                    url = item.Url,
                    thumbnail_url = item.ThumbnailUrl,
                }).ToList(),
                albums = result.Albums?.Select(item => new
                {
                    album_id = item.AlbumId,
                    title = item.Title,
                    media_count = item.MediaCount,
                }).ToList(),
                note = result.Note == null ? null : new
                {
                    note_id = result.Note.NoteId,
                    url = result.Note.Url,
                    title = result.Note.Title,
                    author = result.Note.Author,
                    text = result.Note.Text,
                    thumbnail_url = result.Note.ThumbnailUrl,
                    video_url = result.Note.VideoUrl,
                },
            }));
        }

        // --eval：导航到指定页 → 等它就绪 → 在页面上下文执行一段 JS → 返回值原文写盘 → 退出。
        // 借签名全靠它：签名函数在页面里，让页面替我们算；请求也由页面 fetch 发出，
        // 于是 TLS 指纹、Cookie、Referer 全是浏览器的真实值，不是我们伪造的。
        // 脚本返回的对象会被 WebView2 序列化成 JSON 字符串，C# 侧解一层再落盘。
        private async Task RunEvalAsync()
        {
            string js;
            try
            {
                js = File.ReadAllText(_eval.JsPath, Encoding.UTF8);
            }
            catch (Exception ex)
            {
                Trace.Log("eval: read js failed " + ex.Message);
                Close();
                return;
            }

            try
            {
                SetStatus("eval：导航 " + _eval.NavUrl);
                _core.Navigate(_eval.NavUrl);
                await Task.Delay(_eval.WaitMs);

                var scriptTask = _core.ExecuteScriptAsync(js);
                var guard = Task.Delay(60000);
                if (await Task.WhenAny(scriptTask, guard) == guard)
                {
                    throw new TimeoutException("脚本执行超时 60s（页面可能无响应）");
                }
                string raw = await scriptTask;
                string text = DecodeJsonString(raw);

                // WebView2 的 ExecuteScriptAsync 不 await Promise：async 脚本只会拿到 "{}"。
                // 约定：异步脚本把最终结果挂到 window.__EVAL_RESULT__，这里轮询把它取回来。
                if (string.IsNullOrWhiteSpace(text) || text == "{}" || text == "null")
                {
                    text = null;
                    // 上限放到 400s：批内慢速抓取（每条 6~11 秒）会跑几十秒到几分钟。
                    for (int i = 0; i < 200 && text == null; i++)
                    {
                        await Task.Delay(2000);
                        try
                        {
                            string probe = await _core.ExecuteScriptAsync(
                                "(function(){ if (typeof window.__EVAL_RESULT__ === 'undefined')"
                                + " { return ''; } return JSON.stringify(window.__EVAL_RESULT__); })()");
                            string pv = DecodeJsonString(probe);
                            if (!string.IsNullOrWhiteSpace(pv) && pv != "null" && pv != "{}")
                            {
                                text = pv;
                            }
                        }
                        catch (Exception ex2)
                        {
                            Trace.Log("eval: poll failed " + ex2.Message);
                        }
                    }
                    if (text == null)
                    {
                        text = "TIMEOUT: 400s 内 window.__EVAL_RESULT__ 未出现";
                    }
                }

                File.WriteAllText(_eval.OutPath, text, new UTF8Encoding(false));
                Trace.Log("eval: done -> " + _eval.OutPath + " (" + (text == null ? 0 : text.Length) + " chars)");
                SetStatus("eval 完成");
            }
            catch (Exception ex)
            {
                Trace.Log("eval: ERROR " + ex.GetType().Name + " :: " + ex.Message);
                try
                {
                    File.WriteAllText(
                        _eval.OutPath,
                        "ERROR " + ex.GetType().Name + " :: " + ex.Message,
                        new UTF8Encoding(false));
                }
                catch
                {
                }
            }

            await Task.Delay(300);
            Close();
        }

        // ExecuteScriptAsync 的返回值是 JSON 编码的：字符串会带引号、对象会变成 {...}。
        // 解一层把它还原成原文；解不动就原样返回。
        private static string DecodeJsonString(string raw)
        {
            if (string.IsNullOrEmpty(raw))
            {
                return string.Empty;
            }
            try
            {
                string decoded = JsonSerializer.Deserialize<string>(raw);
                return decoded ?? raw;
            }
            catch
            {
                return raw;
            }
        }

        // 自跑诊断：不等人操作。回到记住的收藏页 → 跑一轮拟人滚动 → 写诊断 → 自动退出。
        // 目的：把「抓到多少条、为什么停在这儿」变成可自证的结论，不必每次麻烦人手动点。
        private async Task RunDiagnoseAsync()
        {
            try
            {
                Trace.Log("diagnose: enter #" + (++_diagnoseRuns));
                SetStatus("诊断模式：等待页面加载…");
                await Task.Delay(3000);

                SetStatus("诊断模式：打开收藏页…");
                await OpenFavoritesAsync();
                await Task.Delay(10000);

                SetStatus("诊断模式：开始拟人滚动…");
                await AutoScrollToEndAsync();

                SetStatus("诊断模式完成：结果见 wb-shell-collect-stats.txt，5 秒后退出。");
                await Task.Delay(5000);
                Close();
            }
            catch (Exception ex)
            {
                Trace.Log("diagnose failed " + ex);
                SetStatus("诊断失败：" + ex.Message);
            }
        }

        // --extract：逐个打开笔记页，只读页面自带的 __INITIAL_STATE__，把正文候选与风控信号落盘。
        // 不构造任何请求、不碰签名；节奏按真人停留（默认 25~60 秒随机），不并发。
        // 一旦命中验证码/登录墙立刻停——这是唯一的硬停止条件，剩下的交给人工判断。
        private async Task RunExtractAsync()
        {
            try
            {
                _extracting = true;
                Trace.Log("extract: enter urls=" + _extract.UrlsPath + " limit=" + _extract.Limit);

                if (!File.Exists(_extract.UrlsPath))
                {
                    Trace.Log("extract: urls file missing");
                    SetStatus("取正文失败：找不到 " + _extract.UrlsPath);
                    Close();
                    return;
                }

                List<string> urls = File.ReadAllLines(_extract.UrlsPath)
                    .Select(x => x.Trim())
                    .Where(x => x.StartsWith("http", StringComparison.OrdinalIgnoreCase))
                    .Take(_extract.Limit)
                    .ToList();

                var rng = new Random();
                int done = 0;
                int withState = 0;
                int withDesc = 0;
                string stopReason = "跑完";

                using (var writer = new StreamWriter(ExtractOutPath, true, new UTF8Encoding(false)))
                {
                    foreach (string url in urls)
                    {
                        done++;
                        Trace.Log("extract: #" + done + " " + url);
                        try
                        {
                            _core.Navigate(url);
                            await Task.Delay(2500 + rng.Next(1500, 4000));

                            var scriptTask = _core.ExecuteScriptAsync(ExtractScript);
                            var guard = Task.Delay(15000);
                            if (await Task.WhenAny(scriptTask, guard) == guard)
                            {
                                throw new TimeoutException("脚本执行超时 15s（页面可能无响应）");
                            }
                            string raw = await scriptTask;
                            string json = raw;
                            try
                            {
                                string decoded = JsonSerializer.Deserialize<string>(raw);
                                if (!string.IsNullOrEmpty(decoded))
                                {
                                    json = decoded;
                                }
                            }
                            catch
                            {
                            }

                            writer.WriteLine(json);
                            writer.Flush();
                            Trace.Log("extract: #" + done + " -> " + json.Length + " chars");

                            bool hasState = false, hasDesc = false, risk = false;
                            try
                            {
                                using (JsonDocument doc = JsonDocument.Parse(json))
                                {
                                    JsonElement root = doc.RootElement;
                                    hasState = root.TryGetProperty("hasState", out JsonElement hs) && hs.GetBoolean();
                                    hasDesc =
                                        (root.TryGetProperty("noteHits", out JsonElement dh) && dh.GetArrayLength() > 0)
                                        || (root.TryGetProperty("descLen", out JsonElement dl) && dl.GetInt32() > 0)
                                        || (root.TryGetProperty("domLen", out JsonElement dom) && dom.GetInt32() > 0);
                                    risk =
                                        (root.TryGetProperty("riskCaptcha", out JsonElement rc) && rc.GetBoolean())
                                        || (root.TryGetProperty("riskLoginWall", out JsonElement rl) && rl.GetBoolean());
                                }
                            }
                            catch (Exception ex)
                            {
                                Trace.Log("extract: parse failed " + ex.Message);
                            }

                            if (hasState) { withState++; }
                            if (hasDesc) { withDesc++; }
                            SetStatus("取正文 " + done + "/" + urls.Count
                                + " · 有状态 " + withState + " · 有正文候选 " + withDesc);

                            if (risk)
                            {
                                stopReason = "命中验证码/登录墙，已停";
                                Trace.Log("extract: risk hit at #" + done);
                                break;
                            }

                            await Task.Delay(rng.Next(_extract.DelayMinSec, _extract.DelayMaxSec) * 1000);
                        }
                        catch (Exception ex)
                        {
                            Trace.Log("extract: #" + done + " ERROR " + ex.GetType().Name + " :: " + ex.Message);
                            string nid = NoteIdFromUrl(url);
                            writer.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
                            {
                                noteId = nid,
                                url = url,
                                error = ex.GetType().Name + " :: " + ex.Message,
                                hasState = false,
                            }));
                            writer.Flush();
                            await Task.Delay(1500);
                        }
                    }
                }

                File.WriteAllText(
                    ExtractStatsPath,
                    "取正文统计\r\n"
                    + "URL 文件：" + _extract.UrlsPath + "\r\n"
                    + "计划条数：" + urls.Count + "　完成：" + done + "\r\n"
                    + "有 __INITIAL_STATE__：" + withState + "\r\n"
                    + "有正文（note 子树字段 或 DOM）：" + withDesc + "\r\n"
                    + "停止原因：" + stopReason + "\r\n"
                    + "明细：" + ExtractOutPath + "\r\n",
                    new UTF8Encoding(false));

                SetStatus("取正文完成：" + done + " 条（" + stopReason + "），明细见 wb-shell-extracted-notes.jsonl");
                await Task.Delay(4000);
                Close();
            }
            catch (Exception ex)
            {
                Trace.Log("extract failed " + ex);
                SetStatus("取正文失败：" + ex.Message);
            }
            finally
            {
                _extracting = false;
            }
        }

        private static string NoteIdFromUrl(string url)
        {
            if (string.IsNullOrEmpty(url)) return "";
            int idx = url.IndexOf("/explore/", StringComparison.OrdinalIgnoreCase);
            if (idx >= 0)
            {
                string tail = url.Substring(idx + 9);
                int end = tail.IndexOf('?');
                if (end >= 0) tail = tail.Substring(0, end);
                return tail.Trim('/');
            }
            return "";
        }

        private static string ResolveProxy()
        {
            string fromEnv = Environment.GetEnvironmentVariable("HTTPS_PROXY");
            if (string.IsNullOrWhiteSpace(fromEnv))
            {
                fromEnv = Environment.GetEnvironmentVariable("HTTP_PROXY");
            }

            if (!string.IsNullOrWhiteSpace(fromEnv))
            {
                return fromEnv.Trim();
            }

            try
            {
                using (Microsoft.Win32.RegistryKey key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Internet Settings"))
                {
                    if (key != null)
                    {
                        object enabled = key.GetValue("ProxyEnable");
                        object server = key.GetValue("ProxyServer");
                        bool on = enabled != null && Convert.ToInt32(enabled) != 0;
                        if (on && server != null)
                        {
                            foreach (string part in server.ToString().Split(';'))
                            {
                                string item = part.Trim();
                                if (item.Length == 0)
                                {
                                    continue;
                                }

                                int equalIndex = item.IndexOf('=');
                                string value = equalIndex >= 0 ? item.Substring(equalIndex + 1) : item;
                                if (value.Length > 0)
                                {
                                    Trace.Log("proxy: from system settings " + value);
                                    return value;
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Trace.Log("proxy: registry read failed " + ex.Message);
            }

            return null;
        }

        private void NavigateTo(int index)
        {
            if (!_ready)
            {
                return;
            }

            _currentPlatform = index;
            string url = Targets[index].HomeUrl;
            _session.Platform = Targets[index].Name;
            SaveSessionState();
            Trace.Log("navigate " + Targets[index].Name + " " + url);
            _core.Navigate(url);
        }

        private void LoadSessionState()
        {
            try
            {
                if (!File.Exists(SessionStatePath))
                {
                    return;
                }

                ShellSessionState state = JsonSerializer.Deserialize<ShellSessionState>(
                    File.ReadAllText(SessionStatePath),
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                if (state == null)
                {
                    return;
                }

                _session.Platform = state.Platform;
                if (state.FavUrls != null)
                {
                    foreach (KeyValuePair<string, string> pair in state.FavUrls)
                    {
                        _session.FavUrls[pair.Key] = pair.Value;
                    }
                }

                Trace.Log("session loaded platform=" + _session.Platform + " favUrls=" + _session.FavUrls.Count);
            }
            catch (Exception ex)
            {
                Trace.Log("load session failed " + ex.Message);
            }
        }

        private void SaveSessionState()
        {
            try
            {
                File.WriteAllText(
                    SessionStatePath,
                    JsonSerializer.Serialize(
                        _session,
                        new JsonSerializerOptions { WriteIndented = true }),
                    new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Trace.Log("save session failed " + ex.Message);
            }
        }

        // 收藏页地址（小红书带 uid、B站带 uid）没法凭空构造，页面自己跳过去时顺手记下来。
        private void RememberFavoriteUrl()
        {
            try
            {
                string url = _core == null ? null : _core.Source;
                if (!IsFavoritesPage(url))
                {
                    return;
                }

                string name = Targets[_currentPlatform].Name;
                string existing;
                if (_session.FavUrls.TryGetValue(name, out existing)
                    && string.Equals(existing, url, StringComparison.Ordinal))
                {
                    return;
                }

                _session.FavUrls[name] = url;
                SaveSessionState();
                Trace.Log("remember fav url " + name + " " + url);
            }
            catch (Exception ex)
            {
                Trace.Log("remember fav url failed " + ex.Message);
            }
        }

        private async Task OpenFavoritesAsync()
        {
            if (!_ready)
            {
                return;
            }

            Target target = Targets[_currentPlatform];
            string url = target.HomeUrl;

            if (target.Name == "bilibili")
            {
                string uid = null;
                try
                {
                    IReadOnlyList<CoreWebView2Cookie> cookies =
                        await _core.CookieManager.GetCookiesAsync("https://www.bilibili.com/");
                    CoreWebView2Cookie match = cookies.FirstOrDefault(
                        item => string.Equals(item.Name, "DedeUserID", StringComparison.OrdinalIgnoreCase));
                    if (match != null && !string.IsNullOrEmpty(match.Value))
                    {
                        uid = match.Value;
                    }
                }
                catch (Exception ex)
                {
                    Trace.Log("favorites: read uid failed " + ex.Message);
                }

                url = string.IsNullOrEmpty(uid)
                    ? "https://space.bilibili.com/"
                    : "https://space.bilibili.com/" + uid + "/favlist";
            }
            else if (target.Name == "zhihu")
            {
                url = "https://www.zhihu.com/collections";
            }
            else
            {
                string remembered;
                if (_session.FavUrls.TryGetValue(target.Name, out remembered)
                    && !string.IsNullOrEmpty(remembered))
                {
                    url = remembered;
                    SetStatus("小红书：回到上次的收藏页（地址已记住）。");
                }
                else
                {
                    SetStatus("小红书：请点页面左侧「我」→「收藏」，本壳会把收藏页地址记下来，下次直接回来。");
                }
            }

            Trace.Log("navigate favorites " + target.Name + " " + url);
            _core.Navigate(url);
        }

        // 自动滚到底（拟人节奏）：驱动方式换成内核真实滚轮事件，不再用脚本给容器赋值 scrollTop。
        // 为什么改用滚轮：真正在滚的是哪一层容器属于页面自己的实现细节，脚本猜错就一点都不滚
        // （09-20 实测就是如此：挑中的伪容器 overflow:visible，赋值被内核忽略，top 恒为 0）。
        // 滚轮交给内核做命中测试，内核自己沿 hover 链找可滚动祖先，而且会真实产生 scroll 事件
        // 与视口变化，懒加载哨兵才有机会被触发。
        // 为什么无规律：人不会匀速等距下拉。这里按概率混合「常态下滑 / 回看 / 快速掠过 / 长停顿」，
        // 步长与间隔都取随机值，避免被页面的滚动节流当成机器行为。
        private async Task AutoScrollToEndAsync()
        {
            if (!_ready || _autoScrolling)
            {
                Trace.Log(
                    "autoscroll: skip #" + (_autoscrollRuns + 1)
                    + " ready=" + _ready + " autoScrolling=" + _autoScrolling);
                return;
            }

            _autoscrollRuns++;
            Trace.Log("autoscroll: enter #" + _autoscrollRuns);

            // 先落一份「滚动开始前」的页面结构快照：tab 与数字角标是静态信息，越早取越保险。
            // 09-21 那轮就是中途窗口被关、报告整份没写出来，白跑一趟；有这份至少结论还在。
            try
            {
                string early = await ReadDomNumbersAsync();
                File.WriteAllText(
                    Path.Combine(Path.GetTempPath(), "wb-shell-page-anatomy.txt"),
                    "# 页面结构快照（滚动开始前）" + Environment.NewLine + Environment.NewLine
                    + (early ?? "(无)") + Environment.NewLine,
                    new UTF8Encoding(false));
                Trace.Log("autoscroll: anatomy snapshot written");
            }
            catch (Exception ex)
            {
                Trace.Log("early anatomy failed " + ex.Message);
            }

            var rng = new Random();
            var roundsSeen = new List<int>();
            var positions = new List<int>();
            var strokes = new List<string>();

            int rounds = 0;
            int idle = 0;
            int stuck = 0;
            int lastPos = -1;
            int lastResponses = _lastCaptureLength;
            bool forced = false;
            bool patientDone = false;
            bool atBottom = false;
            int docHeight = 0;
            int lastIdleDocHeight = 0;
            int idleLimit = 60;   // 还没到底时允许滚久一点，别在半路就收工
            string probeText = "(未读到)";

            _autoScrolling = true;
            SetStatus("自动滚动中（拟人节奏）…准备中");
            try
            {
                ScrollProbe first = await ProbeScrollAsync();
                if (first != null)
                {
                    probeText = DescribeProbe(first);
                    Trace.Log("autoscroll: start probe " + probeText + " url=" + first.Url);
                    if (!IsFavoritesPage(first.Url))
                    {
                        SetStatus("注意：当前不在收藏页 → 请先点「打开我的收藏」。仍在滚动（先让它动起来）…");
                    }

                    // 滚轮需要一个落点，放到列表主体区域（视口中部偏下）。
                    await MoveMouseAsync(
                        Math.Max(80, first.ViewportW / 2),
                        Math.Max(140, (int)(first.ViewportH * 0.55)));
                }

                while (rounds < 400 && idle < idleLimit)
                {
                    rounds++;

                    int roll = rng.Next(100);
                    if (roll < 66)
                    {
                        // 常态浏览：一段连续小幅下滑（像滚轮连转几格），再停一下
                        await HumanStrokeAsync(rng, 3 + rng.Next(4), false);
                        await Task.Delay(300 + rng.Next(1200));
                    }
                    else if (roll < 78)
                    {
                        // 回看：先往上拨一点、停一下，再往下（人扫完一屏常往回瞥一眼）
                        await HumanStrokeAsync(rng, 1 + rng.Next(2), true);
                        await Task.Delay(200 + rng.Next(700));
                        await HumanStrokeAsync(rng, 2 + rng.Next(3), false);
                        await Task.Delay(300 + rng.Next(800));
                    }
                    else if (roll < 88)
                    {
                        // 快速掠过：2~4 下小幅快滚，间隔很短
                        int burst = 2 + rng.Next(3);
                        for (int i = 0; i < burst; i++)
                        {
                            await WheelAsync(WheelStep(rng, true));
                            await Task.Delay(50 + rng.Next(140));
                        }

                        await Task.Delay(220 + rng.Next(500));
                    }
                    else
                    {
                        // 长停顿：像在认真读一条，然后再往下
                        await Task.Delay(1200 + rng.Next(2600));
                        await HumanStrokeAsync(rng, 2 + rng.Next(3), false);
                        await Task.Delay(300 + rng.Next(700));
                    }

                    if (forced)
                    {
                        strokes.Add(await ForceScrollAsync(rng));
                    }

                    await CaptureAsync(silent: true);
                    roundsSeen.Add(_lastCaptureLength);

                    ScrollProbe probe = await ProbeScrollAsync();
                    if (probe != null)
                    {
                        probeText = DescribeProbe(probe);
                        int pos = probe.WindowY + probe.BestTop;
                        positions.Add(pos);
                        stuck = pos == lastPos ? stuck + 1 : 0;
                        lastPos = pos;

                        if (stuck >= 12 && !forced)
                        {
                            forced = true;
                            Trace.Log(
                                "autoscroll: wheel had no effect after " + rounds
                                + " rounds, switching to container scroll | " + probeText);
                        }

                        // 记录页面高度与是否到底：收工判定要用，不能只看响应数。
                        docHeight = probe.DocHeight;
                        atBottom = probe.AtBottom;
                    }

                    if (rounds <= 3 || rounds % 8 == 0)
                    {
                        Trace.Log(
                            "autoscroll round " + rounds + " probe=" + probeText
                            + " responses=" + _lastCaptureLength + " notes=" + _capturedNotes.Count);
                    }

                    SetStatus(
                        "自动滚动中（拟人节奏）…第 " + rounds + " 轮   ｜   页面位移 "
                        + (positions.Count > 0 ? positions[positions.Count - 1] : 0) + "px / 页高 " + docHeight + "px"
                        + (atBottom ? "（已到底）" : "（未到底）")
                        + "   ｜   收藏接口响应 " + _capturedItemCount + " 条   ｜   收藏条目 " + _capturedNotes.Count + " 条"
                        + (forced ? "   ｜   已启用容器兜底" : string.Empty));

                    // 页面还在长高 ⇒ 还在渲染，不算「没动静」。
                    bool pageGrew = docHeight > lastIdleDocHeight;
                    lastIdleDocHeight = docHeight;

                    if (_lastCaptureLength == lastResponses && !pageGrew)
                    {
                        idle++;
                    }
                    else
                    {
                        idle = 0;
                        lastResponses = _lastCaptureLength;
                    }

                    // 还没滚到页面底部，就按更宽的耐心继续往下推；到底了才用紧的收工阈值。
                    idleLimit = atBottom ? 12 : 60;

                    // 连续多轮没有新响应，先别急着收工：懒加载/服务端补数据有时要十几秒。
                    // 这里插一次长等待再轻推几下，仍无新响应才认到底。
                    if (idle == 6 && !patientDone && atBottom)
                    {
                        patientDone = true;
                        SetStatus("已连续 " + idle + " 轮没有新响应，先等 15 秒看会不会补加载…");
                        Trace.Log("autoscroll: idle=" + idle + " -> patient wait 15s");
                        await Task.Delay(15000);
                        await HumanStrokeAsync(rng, 3, false);
                        await Task.Delay(1500);
                        await CaptureAsync(silent: true);
                        roundsSeen.Add(_lastCaptureLength);
                        if (_lastCaptureLength != lastResponses)
                        {
                            idle = 0;
                            lastResponses = _lastCaptureLength;
                        }

                        Trace.Log("autoscroll: patient wait done, responses=" + _lastCaptureLength);
                    }
                }
            }
            catch (Exception ex)
            {
                Trace.Log("autoscroll failed " + ex);
            }
            finally
            {
                _autoScrolling = false;
            }

            await CaptureAsync();
            _lastScrollInfo = probeText;
            _lastScrollTrail = BuildTrail(positions, strokes, forced);
            string numbers = await ReadDomNumbersAsync();
            string bottom = await ReadBottomStateAsync();
            _lastPageChain = await ReadPageChainAsync();
            WriteStats(roundsSeen, numbers, bottom);
            int moved = positions.Count > 1 ? positions[positions.Count - 1] - positions[0] : 0;
            SetStatus(
                "自动滚动结束：" + rounds + " 轮   ｜   页面共移动 " + moved + "px   ｜   收藏接口响应 "
                + _capturedItemCount + " 条（= 页面翻了多少页）   ｜   收藏条目 " + _capturedNotes.Count
                + " 条   →   " + CaptureMdPath);
            Trace.Log(
                "autoscroll: rounds=" + rounds + " moved=" + moved + " responses=" + _capturedItemCount
                + " notes=" + _capturedNotes.Count);
        }

        // 人的步长不是一个定值：常态 240~660，小幅（掠过/回看）120~300。
        private static int WheelStep(Random rng, bool small)
        {
            return small ? 120 + rng.Next(180) : 240 + rng.Next(420);
        }

        // 一次「拟人滚动序列」：真人转滚轮不是一下子跳 500px，而是连续甩出好几个小增量
        // （内核每次只收到几十到一百多 px 的 deltaY），中途还可能手停一下。
        // 对这种靠触底哨兵翻页的列表来说，连续的事件流比单次大跳更接近真人，也更容易把哨兵推进视口。
        private async Task HumanStrokeAsync(Random rng, int steps, bool upward)
        {
            for (int i = 0; i < steps; i++)
            {
                int delta = 70 + rng.Next(120);          // 单次 70~190px，接近真实滚轮一格到几格
                if (upward)
                {
                    delta = -delta;
                }

                await WheelAsync(delta);

                // 步与步之间通常很短；偶尔像手停了一下，间隔明显拉长
                int gap = rng.Next(100) < 18 ? 180 + rng.Next(420) : 35 + rng.Next(95);
                await Task.Delay(gap);
            }
        }

        private async Task MoveMouseAsync(int x, int y)
        {
            _mouseX = x;
            _mouseY = y;
            await DispatchMouseAsync("mouseMoved", 0);
        }

        private async Task WheelAsync(int deltaY)
        {
            await DispatchMouseAsync("mouseWheel", deltaY);
        }

        private async Task DispatchMouseAsync(string type, int deltaY)
        {
            try
            {
                var culture = System.Globalization.CultureInfo.InvariantCulture;
                string payload =
                    "{\"type\":\"" + type + "\",\"x\":" + _mouseX.ToString(culture)
                    + ",\"y\":" + _mouseY.ToString(culture)
                    + ",\"deltaX\":0,\"deltaY\":" + deltaY.ToString(culture)
                    + ",\"modifiers\":0,\"pointerType\":\"mouse\"}";
                await _core.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", payload);
            }
            catch (Exception ex)
            {
                Trace.Log("dispatch " + type + " failed " + ex.Message);
            }
        }

        private async Task<ScrollProbe> ProbeScrollAsync()
        {
            try
            {
                string raw = await _core.ExecuteScriptAsync(ScrollProbeScript);
                string json = JsonSerializer.Deserialize<string>(raw);
                if (string.IsNullOrEmpty(json))
                {
                    return null;
                }

                return JsonSerializer.Deserialize<ScrollProbe>(
                    json,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch (Exception ex)
            {
                Trace.Log("probe failed " + ex.Message);
                return null;
            }
        }

        private async Task<string> ForceScrollAsync(Random rng)
        {
            try
            {
                string raw = await _core.ExecuteScriptAsync(BuildForceScrollScript(WheelStep(rng, false)));
                string text = JsonSerializer.Deserialize<string>(raw);
                return string.IsNullOrEmpty(text) ? raw : text;
            }
            catch (Exception ex)
            {
                Trace.Log("force scroll failed " + ex.Message);
                return "err";
            }
        }

        private static string DescribeProbe(ScrollProbe probe)
        {
            return "windowY=" + probe.WindowY + " bestTop=" + probe.BestTop
                + " room=" + probe.BestRoom + " containers=" + probe.Candidates
                + " best=" + probe.BestTag + " vp=" + probe.ViewportW + "x" + probe.ViewportH;
        }

        private static bool IsFavoritesPage(string url)
        {
            if (string.IsNullOrEmpty(url))
            {
                return false;
            }

            return url.IndexOf("/favlist", StringComparison.OrdinalIgnoreCase) >= 0
                || url.IndexOf("/collections", StringComparison.OrdinalIgnoreCase) >= 0
                || url.IndexOf("tab=fav", StringComparison.OrdinalIgnoreCase) >= 0
                || url.IndexOf("/user/profile/", StringComparison.OrdinalIgnoreCase) >= 0
                || url.IndexOf("/collect", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static string BuildTrail(List<int> positions, List<string> strokes, bool forced)
        {
            if (positions.Count == 0)
            {
                return "(无位移记录：探针没读到页面位置)";
            }

            int first = positions[0];
            int last = positions[positions.Count - 1];
            int max = positions.Max();
            string trail = "起点 " + first + "px → 终点 " + last + "px（净移动 " + (last - first)
                + "px，最大 " + max + "px，采样 " + positions.Count + " 轮）";
            if (forced && strokes.Count > 0)
            {
                trail += "；容器兜底 " + strokes.Count + " 次，末次 " + strokes[strokes.Count - 1];
            }

            return trail;
        }

        private async Task<string> ReadDomNumbersAsync()
        {
            try
            {
                string raw = await _core.ExecuteScriptAsync(DomNumbersScript);
                string inner = JsonSerializer.Deserialize<string>(raw);
                if (string.IsNullOrEmpty(inner))
                {
                    return "(无)";
                }

                using (JsonDocument doc = JsonDocument.Parse(inner))
                {
                    JsonElement root = doc.RootElement;
                    var builder = new StringBuilder();
                    builder.AppendLine();
                    builder.AppendLine("  页面地址：" + FieldText(root, "href"));
                    builder.AppendLine("  页面标题：" + FieldText(root, "title"));
                    builder.AppendLine("  DOM 里真实笔记链接数（去重）：" + FieldText(root, "noteIds")
                        + "   ｜   扫过元素数：" + FieldText(root, "scanned"));
                    builder.AppendLine("  【tab 类元素】");
                    foreach (string line in JsonLines(root, "tabs"))
                    {
                        builder.AppendLine("    - " + line);
                    }

                    builder.AppendLine("  【文字+数字 短标签】");
                    foreach (string line in JsonLines(root, "wordNums"))
                    {
                        builder.AppendLine("    - " + line);
                    }

                    builder.AppendLine("  【count/num 角标】");
                    foreach (string line in JsonLines(root, "counts"))
                    {
                        builder.AppendLine("    - " + line);
                    }

                    builder.AppendLine("  【纯数字叶子（标签=值）】" + string.Join("   ", JsonLines(root, "numbers")));
                    builder.AppendLine("  「加载中」元素祖先链：" + FieldText(root, "loadAncestor"));
                    builder.AppendLine("  人眼所见页面底部原文：" + FieldText(root, "bodyTail"));
                    return builder.ToString();
                }
            }
            catch (Exception ex)
            {
                Trace.Log("dom numbers failed " + ex.Message);
                return null;
            }
        }

        private static IEnumerable<string> JsonLines(JsonElement root, string name)
        {
            JsonElement array;
            if (!root.TryGetProperty(name, out array) || array.ValueKind != JsonValueKind.Array)
            {
                yield break;
            }

            foreach (JsonElement item in array.EnumerateArray())
            {
                yield return item.ToString();
            }
        }

        // 读页面底部状态：DOM 里到底渲染了多少张卡片、有没有「没有更多」提示、有没有失效占位。
        // 用它把「服务端只给了 268」和「页面没渲染出来」这两种情况分开。
        private async Task<string> ReadBottomStateAsync()
        {
            try
            {
                string raw = await _core.ExecuteScriptAsync(BottomStateScript);
                string inner = JsonSerializer.Deserialize<string>(raw);
                if (string.IsNullOrEmpty(inner))
                {
                    return null;
                }

                using (JsonDocument doc = JsonDocument.Parse(inner))
                {
                    JsonElement root = doc.RootElement;
                    string bottomText = FieldText(root, "bottomText");
                    return "DOM卡片数 " + FieldText(root, "cards")
                        + "（选择器 " + FieldText(root, "cardsBySelector") + "）"
                        + "   ｜   失效占位 " + FieldText(root, "expired")
                        + "   ｜   文档高度 " + FieldText(root, "docHeight") + "px"
                        + "   ｜   视口已到底=" + FieldText(root, "atBottom")
                        + "   ｜   底部提示："
                        + (string.IsNullOrEmpty(bottomText) ? "(无)" : bottomText);
                }
            }
            catch (Exception ex)
            {
                Trace.Log("bottom state failed " + ex.Message);
                return null;
            }
        }

        private static string FieldText(JsonElement root, string name)
        {
            JsonElement value;
            if (!root.TryGetProperty(name, out value))
            {
                return "(无)";
            }

            return value.ValueKind == JsonValueKind.String ? value.GetString() : value.ToString();
        }

        // 把 hook 记下的分页链拼成一行可读文本：能一眼看出 cursor 有没有跳、哪一页开始 has_more 变 false。
        private async Task<string> ReadPageChainAsync()
        {
            try
            {
                string raw = await _core.ExecuteScriptAsync("JSON.stringify(window.__wbPageChain || [])");
                string inner = JsonSerializer.Deserialize<string>(raw);
                if (string.IsNullOrEmpty(inner) || inner == "[]")
                {
                    return "(空)";
                }

                var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                List<PageStep> steps = JsonSerializer.Deserialize<List<PageStep>>(inner, options);
                if (steps == null || steps.Count == 0)
                {
                    return "(空)";
                }

                var builder = new StringBuilder();
                for (int i = 0; i < steps.Count; i++)
                {
                    PageStep step = steps[i];
                    builder.Append("#").Append(i + 1)
                        .Append(" 请求=").Append(Short(step.Cursor))
                        .Append(" 返回=").Append(Short(step.NextCursor))
                        .Append(" has_more=").Append(step.HasMore.HasValue ? step.HasMore.Value.ToString() : "?")
                        .Append(" 条数=").Append(step.Count);
                    if (i < steps.Count - 1)
                    {
                        builder.Append("  ／  ");
                    }
                }

                return builder.ToString();
            }
            catch (Exception ex)
            {
                Trace.Log("page chain failed " + ex.Message);
                return null;
            }
        }

        private static string Short(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "(空)";
            }

            return value.Length > 12 ? value.Substring(0, 12) : value;
        }

        private async Task CaptureAsync(bool silent = false)
        {
            if (!_ready)
            {
                return;
            }

            try
            {
                // 先只取条数：内容可能好几 MB，没必要每 5 秒搬一次。
                string lengthRaw = await _core.ExecuteScriptAsync(
                    "String((window.__wbCaptured || []).length)");
                string lengthText = JsonSerializer.Deserialize<string>(lengthRaw);
                int length = 0;
                int.TryParse(lengthText, out length);
                if (silent && length == _lastCaptureLength)
                {
                    return;
                }

                _lastCaptureLength = length;
            }
            catch (Exception ex)
            {
                Trace.Log("capture length probe failed " + ex.Message);
            }
            try
            {
                string raw = await _core.ExecuteScriptAsync("JSON.stringify(window.__wbCaptured || [])");
                string inner = JsonSerializer.Deserialize<string>(raw);
                var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                List<CapturedItem> items = string.IsNullOrEmpty(inner)
                    ? null
                    : JsonSerializer.Deserialize<List<CapturedItem>>(inner, options);

                if (items == null || items.Count == 0)
                {
                    if (!silent)
                    {
                        SetStatus("还没接住东西：先在收藏页滚动几屏（让页面自己翻页），再点「抓取本页内容」。");
                    }

                    Trace.Log("capture: nothing yet");
                    return;
                }

                _capturedItemCount = items.Count;

                int before = _capturedNotes.Count;
                foreach (CapturedItem item in items)
                {
                    foreach (CapturedNote note in ExtractNotes(item.Url, item.Body))
                    {
                        bool exists = _capturedNotes.Any(
                            existing => string.Equals(existing.Platform, note.Platform, StringComparison.OrdinalIgnoreCase)
                                && string.Equals(existing.Id, note.Id, StringComparison.Ordinal));
                        if (!exists)
                        {
                            _capturedNotes.Add(note);
                        }
                    }
                }

                WriteCaptureFiles(items);
                if (!silent || _capturedNotes.Count != before)
                {
                    SetStatus(
                        "接住 " + items.Count + " 条响应，收藏条目 " + _capturedNotes.Count
                        + " 条（新增 " + (_capturedNotes.Count - before) + "）→ " + CaptureMdPath);
                    Trace.Log("capture: responses=" + items.Count + " notes=" + _capturedNotes.Count);
                }
            }
            catch (Exception ex)
            {
                Trace.Log("capture failed " + ex);
                SetStatus("抓取失败：" + ex.Message);
            }
        }

        // 当前只解析小红书收藏分页；B站 / 知乎的收藏结构待 R5 按其字段接入。
        // 字段名做容忍匹配：平台改版时先改这里，不要假设只有一种形状。
        private static IEnumerable<CapturedNote> ExtractNotes(string url, string body)
        {
            var notes = new List<CapturedNote>();
            if (string.IsNullOrEmpty(body))
            {
                return notes;
            }

            if (GuessPlatform(url) != "xiaohongshu")
            {
                return notes;
            }

            try
            {
                using (JsonDocument document = JsonDocument.Parse(body))
                {
                    JsonElement root = document.RootElement;
                    JsonElement data;
                    if (!TryGet(root, "data", out data))
                    {
                        data = root;
                    }

                    JsonElement list;
                    if (!TryFindArray(data, out list))
                    {
                        return notes;
                    }

                    foreach (JsonElement note in list.EnumerateArray())
                    {
                        string id = FirstString(note, IdKeys);
                        if (string.IsNullOrEmpty(id))
                        {
                            continue;
                        }

                        // 实测：收藏分页的条目是「扁平结构」（note_id / title / type / user.nickname），
                        // 与详情类接口的 note_card 嵌套结构不同，两种都认。
                        JsonElement card;
                        JsonElement source = TryGet(note, "note_card", out card) ? card : note;

                        string token = FirstString(note, XsecKeys);
                        string xsecSource = FirstString(note, XsecSourceKeys);
                        if (string.IsNullOrEmpty(xsecSource)) xsecSource = FirstString(source, XsecSourceKeys);
                        string noteUrl = "https://www.xiaohongshu.com/explore/" + id;
                        if (!string.IsNullOrEmpty(token) && !string.IsNullOrEmpty(xsecSource))
                        {
                            noteUrl += "?xsec_token=" + Uri.EscapeDataString(token)
                                + "&xsec_source=" + Uri.EscapeDataString(xsecSource);
                        }

                        notes.Add(new CapturedNote
                        {
                            Platform = "xiaohongshu",
                            Id = id,
                            Title = FirstString(source, TitleKeys),
                            Type = FirstString(source, TypeKeys),
                            Author = Str(source, "user", "nickname"),
                            Url = noteUrl,
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                Trace.Log("extract failed " + ex.Message);
            }

            return notes;
        }

        private static readonly string[] ListKeys =
            new[] { "notes", "items", "note_list", "list", "data" };

        private static readonly string[] IdKeys =
            new[] { "note_id", "id", "noteId" };

        private static readonly string[] TitleKeys =
            new[] { "display_title", "title" };

        private static readonly string[] TypeKeys =
            new[] { "type", "note_type" };

        private static readonly string[] XsecKeys =
            new[] { "xsec_token", "xsecToken" };

        private static readonly string[] XsecSourceKeys =
            new[] { "xsec_source", "xsecSource" };

        private static bool TryGet(JsonElement element, string key, out JsonElement value)
        {
            if (element.ValueKind == JsonValueKind.Object && element.TryGetProperty(key, out value))
            {
                return true;
            }

            value = default(JsonElement);
            return false;
        }

        private static bool TryFindArray(JsonElement data, out JsonElement list)
        {
            list = default(JsonElement);
            if (data.ValueKind == JsonValueKind.Array)
            {
                list = data;
                return true;
            }

            if (data.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            foreach (string key in ListKeys)
            {
                JsonElement candidate;
                if (data.TryGetProperty(key, out candidate) && candidate.ValueKind == JsonValueKind.Array)
                {
                    list = candidate;
                    return true;
                }
            }

            return false;
        }

        private static string FirstString(JsonElement element, string[] keys)
        {
            foreach (string key in keys)
            {
                string value = Str(element, key);
                if (!string.IsNullOrEmpty(value))
                {
                    return value;
                }
            }

            return null;
        }

        private static string Str(JsonElement element, params string[] path)
        {
            JsonElement current = element;
            foreach (string key in path)
            {
                if (current.ValueKind != JsonValueKind.Object)
                {
                    return null;
                }

                JsonElement next;
                if (!current.TryGetProperty(key, out next))
                {
                    return null;
                }

                current = next;
            }

            if (current.ValueKind == JsonValueKind.String)
            {
                return current.GetString();
            }

            if (current.ValueKind == JsonValueKind.Null || current.ValueKind == JsonValueKind.Undefined)
            {
                return null;
            }

            return current.ToString();
        }

        // 读分页响应里的 has_more：用它判断「页面是到底了」还是「页面被中止了」。
        private static bool TryReadHasMore(string body, out bool hasMore)
        {
            hasMore = false;
            if (string.IsNullOrEmpty(body))
            {
                return false;
            }

            try
            {
                using (JsonDocument document = JsonDocument.Parse(body))
                {
                    JsonElement root = document.RootElement;
                    JsonElement data;
                    if (!TryGet(root, "data", out data))
                    {
                        data = root;
                    }

                    foreach (string key in new[] { "has_more", "hasMore" })
                    {
                        JsonElement value;
                        if (TryGet(data, key, out value)
                            && (value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False))
                        {
                            hasMore = value.GetBoolean();
                            return true;
                        }
                    }
                }
            }
            catch
            {
                // 结构不认识就当读不到，不影响主流程。
            }

            return false;
        }

        private void WriteStats(List<int> roundsSeen, string domNumbers, string bottomState)
        {
            try
            {
                var builder = new StringBuilder();
                builder.AppendLine("# 收藏抓取诊断（实验）");
                builder.AppendLine();
                builder.AppendLine("- 生成时间：" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                builder.AppendLine("- 收藏接口响应（= 页数）：" + _capturedItemCount + " 条");
                builder.AppendLine("- 去重后收藏条目：" + _capturedNotes.Count + " 条");
                builder.AppendLine("- 末页 has_more：" + _lastHasMore);
                builder.AppendLine("- 各页条目数：" + string.Join(", ", _lastPageCounts));
                builder.AppendLine("- 分页链（请求cursor → 返回cursor / has_more / 条数）：" + (_lastPageChain ?? "(未读到)"));
                builder.AppendLine("- 页面底部状态：" + (bottomState ?? "(未读到)"));
                builder.AppendLine("- 页面结构与页面自称的总数（核对 423 的口径用）：" + (domNumbers ?? "(无)"));
                builder.AppendLine("- 自动滚动过程中「已接住的响应数」变化：" + string.Join(" → ", roundsSeen));
                builder.AppendLine("- 页面位移轨迹：" + (_lastScrollTrail ?? "(无)"));
                builder.AppendLine("- 最后一次页面位置探针：" + (_lastScrollInfo ?? "(无)"));
                builder.AppendLine();
                builder.AppendLine("判据一（滚动有没有效）：位移净移动≈0 且 响应数不变 ⇒ 滚动没驱动页面；");
                builder.AppendLine("判据二（到底是谁的账）：位移在涨 且 响应数不变时，看末页 has_more 与 DOM 卡片数 ——");
                builder.AppendLine("      has_more=false 且 DOM卡片数≈已抓条目数 ⇒ 服务端就只给这么多，缺口不在抓取层；");
                builder.AppendLine("      has_more=true  且 DOM卡片数>已抓条目数 ⇒ 页面被中止（滚动没触发继续加载）；");
                builder.AppendLine("      底部出现「没有更多 / 到底」提示 ⇒ 服务端明确收尾，同第一种。");

                File.WriteAllText(CaptureStatsPath, builder.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Trace.Log("write stats failed " + ex.Message);
            }
        }

        private void WriteCaptureFiles(List<CapturedItem> items)
        {
            try
            {
                File.WriteAllText(
                    CaptureJsonPath,
                    JsonSerializer.Serialize(
                        _capturedNotes,
                        new JsonSerializerOptions { WriteIndented = true }),
                    new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Trace.Log("write capture json failed " + ex.Message);
            }

            try
            {
                var pageCounts = new List<int>();
                string hasMore = "(未读到)";
                foreach (CapturedItem item in items)
                {
                    pageCounts.Add(ExtractNotes(item.Url, item.Body).Count());

                    bool more;
                    if (TryReadHasMore(item.Body, out more))
                    {
                        hasMore = more ? "true（页面上还有更多）" : "false（页面自称已到底）";
                    }
                }

                _lastPageCounts = pageCounts;
                _lastHasMore = hasMore;

                int parsed = pageCounts.Count(count => count > 0);
                int sum = pageCounts.Sum();

                var builder = new StringBuilder();
                builder.AppendLine("# 抓取到的收藏条目（实验）");
                builder.AppendLine();
                builder.AppendLine("- 生成时间：" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                builder.AppendLine("- 来源：登录壳内接住页面自身发出的收藏列表响应（未自行计算签名）");
                builder.AppendLine("- 收藏接口响应：" + items.Count + " 条　←　这个数字等于「页面翻了多少页」，不是条目数");
                builder.AppendLine("- 其中能解析出列表的响应：" + parsed + " 条");
                builder.AppendLine("- 各页条目数合计（未去重）：" + sum + " 条");
                builder.AppendLine("- 去重后条目：" + _capturedNotes.Count + " 条");
                builder.AppendLine("- 末页 has_more：" + hasMore);
                builder.AppendLine();
                builder.AppendLine("| # | 类型 | 标题 | 作者 | 链接 |");
                builder.AppendLine("|---|---|---|---|---|");

                int index = 1;
                foreach (CapturedNote note in _capturedNotes)
                {
                    builder.AppendLine(
                        "| " + index + " | " + Clean(note.Type) + " | " + Clean(note.Title)
                        + " | " + Clean(note.Author) + " | " + Clean(note.Url) + " |");
                    index++;
                }

                File.WriteAllText(CaptureMdPath, builder.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Trace.Log("write capture md failed " + ex.Message);
            }

            WriteRawDump(items);
        }

        // 诊断用：把接住的原始响应落盘，用于核对接口字段结构（每条只留前 1200 字符）。
        private void WriteRawDump(List<CapturedItem> items)
        {
            try
            {
                var builder = new StringBuilder();
                builder.AppendLine("# 接住的原始响应（每条前 1200 字符，用于核对字段结构）");
                builder.AppendLine();

                int index = 1;
                foreach (CapturedItem item in items)
                {
                    string body = item.Body ?? string.Empty;
                    builder.AppendLine("## " + index + " · " + item.Url);
                    builder.AppendLine("- 字符数：" + body.Length);
                    builder.AppendLine("```");
                    builder.AppendLine(body.Length > 1200 ? body.Substring(0, 1200) : body);
                    builder.AppendLine("```");
                    builder.AppendLine();
                    index++;
                }

                File.WriteAllText(CaptureRawPath, builder.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Trace.Log("write raw dump failed " + ex.Message);
            }
        }

        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return string.Empty;
            }

            return text.Replace("|", "\\|").Replace("\r", " ").Replace("\n", " ").Trim();
        }

        private async Task CollectAllAsync()
        {
            if (!_ready)
            {
                return;
            }

            _snapshots.Clear();
            foreach (Target target in Targets)
            {
                try
                {
                    IReadOnlyList<CoreWebView2Cookie> cookies =
                        await _core.CookieManager.GetCookiesAsync(target.CookieUri);

                    var snapshot = new CookieSnapshot
                    {
                        Name = target.Name,
                        Count = cookies.Count,
                        NonEmpty = cookies.Count(item => !string.IsNullOrEmpty(item.Value)),
                        CookieNames = cookies
                            .Select(item => item.Name)
                            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
                            .ToList(),
                        HttpOnlyNames = cookies
                            .Where(item => item.IsHttpOnly)
                            .Select(item => item.Name)
                            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
                            .ToList(),
                        LoginCookiesPresent = cookies
                            .Where(item => target.LoginCookies.Contains(
                                item.Name, StringComparer.OrdinalIgnoreCase))
                            .Where(item => !string.IsNullOrEmpty(item.Value))
                            .Select(item => item.Name)
                            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
                            .ToList(),
                    };

                    snapshot.LoggedIn = snapshot.LoginCookiesPresent.Count > 0;
                    _snapshots.Add(snapshot);
                }
                catch (Exception ex)
                {
                    Trace.Log("collect " + target.Name + " failed " + ex.Message);
                }
            }

            UpdateStatusLabel();
        }

        private void UpdateStatusLabel()
        {
            if (_snapshots.Count == 0)
            {
                return;
            }

            string current = Targets[_currentPlatform].Display;
            string url = "?";
            try
            {
                url = _core == null ? "?" : _core.Source;
            }
            catch
            {
                url = "?";
            }

            var parts = new List<string>();
            foreach (CookieSnapshot snapshot in _snapshots)
            {
                Target target = Targets.First(item => item.Name == snapshot.Name);
                parts.Add(
                    target.Display + (snapshot.LoggedIn
                        ? " 已登录(" + string.Join("/", snapshot.LoginCookiesPresent) + ")"
                        : " 未登录"));
            }

            SetStatus(
                "当前：" + current
                + "    ｜    " + string.Join(" · ", parts)
                + "    ｜    已记录接口响应 " + _responses.Count + " 条"
                + "    ｜    收藏接口响应 " + _capturedItemCount + " 条(=页数)"
                + "    ｜    收藏条目 " + _capturedNotes.Count + " 条");
            Trace.Log("status current=" + current + " url=" + url + " | " + string.Join(", ", parts));
        }

        private void SetStatus(string text)
        {
            if (_status.IsDisposed)
            {
                return;
            }

            _status.Text = text;
        }

        private void OnResponseReceived(
            object sender,
            CoreWebView2WebResourceResponseReceivedEventArgs args)
        {
            try
            {
                string uri = args.Request.Uri;
                if (string.IsNullOrEmpty(uri))
                {
                    return;
                }

                bool interesting =
                    uri.IndexOf("/api/", StringComparison.OrdinalIgnoreCase) >= 0
                    || uri.IndexOf("collect", StringComparison.OrdinalIgnoreCase) >= 0
                    || uri.IndexOf("fav", StringComparison.OrdinalIgnoreCase) >= 0
                    || uri.IndexOf("qrcode", StringComparison.OrdinalIgnoreCase) >= 0;

                if (!interesting)
                {
                    return;
                }

                int statusCode = 0;
                try
                {
                    statusCode = args.Response.StatusCode;
                }
                catch
                {
                    statusCode = 0;
                }

                string contentType = null;
                try
                {
                    if (args.Response.Headers != null && args.Response.Headers.Contains("Content-Type"))
                    {
                        contentType = args.Response.Headers.GetHeader("Content-Type");
                    }
                }
                catch
                {
                    contentType = null;
                }

                string platform = GuessPlatform(uri);
                bool favoriteRelated = false;
                foreach (Target target in Targets)
                {
                    if (string.Equals(target.Name, platform, StringComparison.OrdinalIgnoreCase))
                    {
                        favoriteRelated = target.FavoriteApiHints.Any(
                            hint => uri.IndexOf(hint, StringComparison.OrdinalIgnoreCase) >= 0);
                        break;
                    }
                }

                if (_responses.Count < 600 || _responses.ContainsKey(uri))
                {
                    _responses[uri] = new
                    {
                        uri,
                        platform,
                        status = statusCode,
                        content_type = contentType,
                        favorite_related = favoriteRelated,
                        observed_at = DateTime.Now.ToString("HH:mm:ss"),
                    };
                }
            }
            catch
            {
                // A single failed inspection must not abort the run.
            }
        }

        private static string GuessPlatform(string uri)
        {
            string host = string.Empty;
            try
            {
                host = new Uri(uri).Host;
            }
            catch
            {
                return "unknown";
            }

            if (host.IndexOf("bilibili", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "bilibili";
            }

            if (host.IndexOf("zhihu", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "zhihu";
            }

            if (host.IndexOf("xiaohongshu", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "xiaohongshu";
            }

            return "other";
        }

        private void WriteReport(string reason)
        {
            try
            {
                var favoriteResponses = _responses.Values
                    .Where(item =>
                    {
                        using (JsonDocument document = JsonDocument.Parse(
                            JsonSerializer.Serialize(item)))
                        {
                            JsonElement flag;
                            return document.RootElement.TryGetProperty("favorite_related", out flag)
                                && flag.GetBoolean();
                        }
                    })
                    .ToList();

                object report = new
                {
                    status = _ready ? "ok" : "not-ready",
                    reason,
                    generated_at = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"),
                    shell = "interactive login shell (WebView2)",
                    report_note = "Cookie values are intentionally not recorded; only names and flags.",
                    engine_version = _engineVersion,
                    proxy = _proxyNote,
                    current_platform = Targets[_currentPlatform].Name,
                    current_url = _core == null ? null : _core.Source,
                    platforms = _snapshots,
                    intercepted_api_response_count = _responses.Count,
                    intercepted_api_responses = _responses.Values.ToList(),
                    favorite_related_response_count = favoriteResponses.Count,
                    favorite_related_responses = favoriteResponses,
                    captured_note_count = _capturedNotes.Count,
                };

                string json = JsonSerializer.Serialize(
                    report,
                    new JsonSerializerOptions { WriteIndented = true });

                File.WriteAllText(ReportPath, json, new UTF8Encoding(false));
                Trace.Log("report written reason=" + reason);
            }
            catch (Exception ex)
            {
                Trace.Log("report failed " + ex);
            }
        }
    }

    internal sealed class XhsSessionResult
    {
        public string Status { get; }
        public string Message { get; }
        public string BrowserProfile { get; }
        public bool SessionInvalidated { get; }
        public bool Progress { get; }
        public IReadOnlyList<XhsFavoriteCandidate> Candidates { get; }
        public IReadOnlyList<XhsFavoriteAlbum> Albums { get; }
        public XhsNoteDetail Note { get; }
        public bool? CollectionRestored { get; }

        public XhsSessionResult(
            string status,
            string message,
            string browserProfile = null,
            bool sessionInvalidated = false,
            IReadOnlyList<XhsFavoriteCandidate> candidates = null,
            IReadOnlyList<XhsFavoriteAlbum> albums = null,
            bool progress = false,
            XhsNoteDetail note = null,
            bool? collectionRestored = null)
        {
            Status = status;
            Message = message;
            BrowserProfile = browserProfile;
            SessionInvalidated = sessionInvalidated;
            Candidates = candidates;
            Albums = albums;
            Progress = progress;
            Note = note;
            CollectionRestored = collectionRestored;
        }
    }

    internal sealed class XhsFavoriteAlbum
    {
        public string AlbumId { get; set; }
        public string Title { get; set; }
        public int? MediaCount { get; set; }
    }

    internal sealed class XhsNoteDetail
    {
        public string NoteId { get; set; }
        public string Url { get; set; }
        public string Title { get; set; }
        public string Author { get; set; }
        public string Text { get; set; }
        public string ThumbnailUrl { get; set; }
        public string VideoUrl { get; set; }
    }

    internal sealed class XhsFavoriteCandidate
    {
        public string CandidateId { get; set; }
        public string Id { get; set; }
        public string Title { get; set; }
        public string Author { get; set; }
        public string Type { get; set; }
        public string Url { get; set; }
        public string ThumbnailUrl { get; set; }
        internal bool HasOriginalDomUrl { get; set; }
    }

    internal sealed class XhsLoginForm : Form
    {
        private const string ExploreUrl = "https://www.xiaohongshu.com/explore";
        private const string UserMePath = "/api/sns/web/v2/user/me";
        private const string FavoritePagePath = "/api/sns/web/v2/note/collect/page";
        private const string BoardNotePath = "/api/sns/web/v1/board/note";
        private const int CheckTimeoutMilliseconds = 12000;

        private readonly CoreWebView2Environment _environment;
        private readonly string _browserProfile;
        private readonly WebView2 _view = new WebView2();
        private readonly Label _windowStatus = new Label();
        private readonly Button _copyLink = new Button();
        private readonly Button _recheck = new Button();
        private readonly System.Threading.SemaphoreSlim _checkGate =
            new System.Threading.SemaphoreSlim(1, 1);
        private CoreWebView2 _core;
        private TaskCompletionSource<UserMeEvidence> _userMeWaiter;
        private TaskCompletionSource<FavoriteEvidence> _favoriteWaiter;
        private readonly object _favoriteScanLock = new object();
        private readonly List<XhsFavoriteCandidate> _favoriteScanCandidates = new List<XhsFavoriteCandidate>();
        private readonly HashSet<string> _favoriteScanIds = new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> _favoriteAlbumUrls = new Dictionary<string, string>(StringComparer.Ordinal);
        private TaskCompletionSource<FavoriteEvidence> _favoriteScanWaiter;
        private readonly Dictionary<string, Queue<(string ScanId, int Number, long Started)>> _favoritePageRequests
            = new Dictionary<string, Queue<(string, int, long)>>(StringComparer.Ordinal);
        private int _favoritePageRequestNumber;
        private FavoriteEvidence _favoriteLastPage;
        private string _favoriteScanRequestId;
        private string _favoriteScanScope;
        private string _favoriteScanAlbumId;
        private string _favoriteScanCollectionUrl;
        private string _favoriteReadScope;
        private string _favoriteReadAlbumId;
        private int _favoriteReadCandidateIndex = -1;
        private bool _favoriteScanActive;
        private bool _favoriteScanIsAlbum;
        private bool _favoriteScanCancelled;
        private string _favoriteDirectoryUrl;
        private bool _initialized;
        private bool _shuttingDown;
        private bool _riskControlled;

        public event EventHandler UserRequestedClose;
        public event Action<string, IReadOnlyList<XhsFavoriteCandidate>> FavoriteScanProgress;

        public XhsLoginForm(CoreWebView2Environment environment, string browserProfile)
        {
            _environment = environment;
            _browserProfile = browserProfile;
            Text = "小红书登录";
            Width = 1080;
            Height = 780;
            StartPosition = FormStartPosition.CenterParent;

            var actions = new TableLayoutPanel
            {
                Dock = DockStyle.Top,
                Height = 44,
                ColumnCount = 3,
                Padding = new Padding(10, 7, 10, 7),
            };
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            _windowStatus.Dock = DockStyle.Fill;
            _windowStatus.TextAlign = System.Drawing.ContentAlignment.MiddleLeft;
            _windowStatus.AutoEllipsis = true;
            _windowStatus.Text = "请在下方小红书网页中登录或浏览，完成后点击“重新检查”";
            _copyLink.AutoSize = true;
            _copyLink.Text = "复制当前链接";
            _copyLink.Click += CopyCurrentLink;
            _recheck.AutoSize = true;
            _recheck.Text = "重新检查";
            _recheck.Click += RecheckSession;
            actions.Controls.Add(_windowStatus, 0, 0);
            actions.Controls.Add(_copyLink, 1, 0);
            actions.Controls.Add(_recheck, 2, 0);

            _view.Dock = DockStyle.Fill;
            Controls.Add(_view);
            Controls.Add(actions);
            FormClosing += OnFormClosing;
        }

        public async Task InitializeAsync()
        {
            if (_initialized)
            {
                return;
            }

            await _view.EnsureCoreWebView2Async(_environment);
            _core = _view.CoreWebView2;
            _core.AddWebResourceRequestedFilter("https://*/api/sns/web/*", CoreWebView2WebResourceContext.All);
            _core.WebResourceRequested += OnFavoritePageRequested;
            _core.WebResourceResponseReceived += OnResponseReceived;
            _initialized = true;
            await NavigateAndWaitAsync(ExploreUrl);
        }

        public async Task<XhsSessionResult> CheckSessionAsync()
        {
            await _checkGate.WaitAsync();
            try
            {
                await InitializeAsync();
                _riskControlled = false;
                _favoriteWaiter = null;
                _userMeWaiter = NewWaiter<UserMeEvidence>();

                bool loaded = await NavigateAndWaitAsync(ExploreUrl);
                if (!loaded)
                {
                    return await RiskOrUnavailableAsync("小红书页面未能加载，登录状态暂时无法确认");
                }

                if (await IsLoginWallAsync())
                {
                    return Result("NOT_CONNECTED", "小红书页面要求登录", sessionInvalidated: true);
                }

                UserMeEvidence user = await WaitForResponseAsync(_userMeWaiter.Task);
                _userMeWaiter = null;
                if (user == null)
                {
                    return await RiskOrUnavailableAsync("未收到小红书账号状态响应，登录状态暂时无法确认");
                }

                if (user.IsAnonymous)
                {
                    return Result("NOT_CONNECTED", "未检测到小红书登录账号", sessionInvalidated: true);
                }

                if (!user.HasUserId || string.IsNullOrWhiteSpace(user.UserId))
                {
                    return await RiskOrUnavailableAsync("未检测到可用于检查收藏页的登录账号");
                }

                _favoriteWaiter = NewWaiter<FavoriteEvidence>();
                string favoriteUrl =
                    "https://www.xiaohongshu.com/user/profile/"
                    + Uri.EscapeDataString(user.UserId)
                    + "?tab=fav&subTab=note";
                loaded = await NavigateAndWaitAsync(favoriteUrl);
                if (!loaded)
                {
                    return await RiskOrUnavailableAsync("小红书收藏页未能加载，登录状态暂时无法确认");
                }

                FavoriteEvidence favorite = await WaitForResponseAsync(_favoriteWaiter.Task);
                _favoriteWaiter = null;
                if (_riskControlled || (favorite != null && favorite.IsRiskControlled))
                {
                    return await RiskOrUnavailableAsync("小红书收藏业务响应暂时无法确认登录状态");
                }

                bool loginWall = await IsLoginWallAsync();
                bool expectedPage = IsExpectedFavoritePage(user.UserId);
                if (expectedPage && !loginWall && favorite != null && favorite.IsAuthenticatedBusinessResponse)
                {
                    return Result("CONNECTED", "小红书登录已通过页面业务响应确认");
                }

                if (favorite != null && favorite.IsAnonymous)
                {
                    return Result("NOT_CONNECTED", "小红书收藏页未确认登录状态", sessionInvalidated: true);
                }

                return Result(
                    "REAUTH_REQUIRED",
                    loginWall
                        ? "小红书页面仍显示登录或验证入口，请完成后再检查"
                        : !expectedPage
                            ? "小红书收藏页发生跳转，登录状态暂时无法确认"
                        : "小红书收藏业务响应未能确认登录状态");
            }
            finally
            {
                _userMeWaiter = null;
                _favoriteWaiter = null;
                _checkGate.Release();
            }
        }

        public async Task<XhsSessionResult> ScanFavoritesAsync(string requestId, string scope, string albumId)
        {
            scope = string.IsNullOrWhiteSpace(scope) ? "notes" : scope;
            if (scope != "directory" && scope != "notes" && scope != "album")
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书收藏范围无法确认", _browserProfile);
            }
            Trace.LogAlways("xhs-scan op=" + Trace.XhsId(requestId) + " event=start scope=" + scope + " album=" + Trace.XhsId(albumId));
            lock (_favoriteScanLock)
            {
                if (!string.IsNullOrEmpty(_favoriteScanRequestId))
                {
                    return new XhsSessionResult("REAUTH_REQUIRED", "小红书收藏扫描正在进行", _browserProfile);
                }
                string selectedAlbumUrl = null;
                if (scope == "album" && (string.IsNullOrWhiteSpace(albumId)
                    || !_favoriteAlbumUrls.TryGetValue(albumId, out selectedAlbumUrl)))
                {
                    return new XhsSessionResult("REAUTH_REQUIRED", "小红书专辑目录已失效，请重新读取", _browserProfile);
                }
                _favoriteScanRequestId = requestId;
                _favoriteLastPage = null;
                _favoriteScanCancelled = false;
                _favoriteScanActive = false;
                _favoriteScanIsAlbum = scope == "album";
                if (scope == "directory") _favoriteAlbumUrls.Clear();
            }
            await _checkGate.WaitAsync();
            try
            {
                lock (_favoriteScanLock)
                {
                    _favoriteScanScope = scope;
                    _favoriteScanAlbumId = scope == "album" ? albumId : null;
                    _favoriteScanCollectionUrl = null;
                    _favoriteReadScope = null;
                    _favoriteReadAlbumId = null;
                    _favoriteReadCandidateIndex = -1;
                }
                if (FavoriteScanCancelled(requestId))
                {
                    return new XhsSessionResult("PARTIAL", "小红书收藏读取已取消", _browserProfile);
                }
                await InitializeAsync();
                _riskControlled = false;
                _favoriteWaiter = null;
                _userMeWaiter = NewWaiter<UserMeEvidence>();
                bool loaded = await NavigateAndWaitAsync(ExploreUrl);
                if (!loaded)
                {
                    return await RiskOrUnavailableAsync("小红书页面未能加载，登录状态暂时无法确认");
                }
                if (FavoriteScanCancelled(requestId))
                {
                    return new XhsSessionResult("PARTIAL", "小红书收藏读取已取消", _browserProfile);
                }

                UserMeEvidence user = await WaitForResponseAsync(_userMeWaiter.Task);
                _userMeWaiter = null;
                if (user == null)
                {
                    return await RiskOrUnavailableAsync("未收到小红书账号状态响应，登录状态暂时无法确认");
                }
                if (user.IsAnonymous)
                {
                    return Result("NOT_CONNECTED", "未检测到小红书登录账号", sessionInvalidated: true);
                }
                if (!user.HasUserId || string.IsNullOrWhiteSpace(user.UserId))
                {
                    return await RiskOrUnavailableAsync("未检测到可用于读取收藏页的登录账号");
                }
                if (FavoriteScanCancelled(requestId))
                {
                    return new XhsSessionResult("PARTIAL", "小红书收藏读取已取消", _browserProfile);
                }
                if (scope == "directory")
                {
                    return await ScanFavoriteDirectoryAsync(requestId, user.UserId);
                }
                if (scope == "album")
                {
                    string albumUrl;
                    lock (_favoriteScanLock)
                    {
                        _favoriteAlbumUrls.TryGetValue(albumId, out albumUrl);
                        _favoriteScanCollectionUrl = albumUrl;
                    }
                    return await ScanFavoriteAlbumAsync(requestId, albumUrl);
                }

                lock (_favoriteScanLock)
                {
                    _favoriteScanCandidates.Clear();
                    _favoriteScanIds.Clear();
                    _favoriteScanActive = true;
                    _favoriteScanIsAlbum = false;
                    _favoriteScanWaiter = NewWaiter<FavoriteEvidence>();
                }

                string favoriteUrl = "https://www.xiaohongshu.com/user/profile/"
                    + Uri.EscapeDataString(user.UserId) + "?tab=fav&subTab=note";
                lock (_favoriteScanLock) _favoriteScanCollectionUrl = favoriteUrl;
                loaded = await NavigateAndWaitAsync(favoriteUrl);
                if (!loaded)
                {
                    if (FavoriteScanCancelled(requestId)) return FinishFavoriteScan(requestId, null, "收藏");
                    return await RiskOrUnavailableAsync("小红书收藏页未能加载");
                }
                if (FavoriteScanCancelled(requestId))
                {
                    return FinishFavoriteScan(requestId, null, "收藏");
                }

                TaskCompletionSource<FavoriteEvidence> firstWaiter;
                lock (_favoriteScanLock) firstWaiter = _favoriteScanWaiter;
                List<XhsFavoriteCandidate> domFirst = await ReadFavoriteNotesFromDomAsync(requestId, false);
                Trace.LogAlways("xhs-scan op=" + requestId + " event=first_dom count=" + domFirst.Count);
                FavoriteEvidence page;
                if (domFirst.Count > 0)
                {
                    // 首屏可能由服务端渲染，页面不发起收藏接口请求；先读 DOM，再滚动触发后续分页。
                    MergeFavoriteCandidates(domFirst);
                    FavoriteEvidence firstPage = firstWaiter.Task.IsCompletedSuccessfully ? firstWaiter.Task.Result : null;
                    // 首屏 DOM 已有内容而接口回空页：不把这次空数据当成末页证据，继续滚动读真实分页。
                    page = firstPage != null && !(firstPage.IsEmptyPage && !firstPage.HasMore)
                        ? firstPage
                        : new FavoriteEvidence { IsAuthenticatedBusinessResponse = true, HasMore = true };
                }
                else
                {
                    page = await WaitForResponseAsync(firstWaiter.Task);
                    if (page == null || FavoriteScanCancelled(requestId))
                    {
                        return FinishFavoriteScan(requestId, page, "收藏");
                    }
                }
                if (page.IsRiskControlled || _riskControlled)
                {
                    return FinishFavoriteScan(requestId, page, "收藏");
                }
                if (page.IsAnonymous || await IsLoginWallAsync())
                {
                    return Result("NOT_CONNECTED", "小红书收藏页未确认登录状态", sessionInvalidated: true);
                }
                if (!page.IsAuthenticatedBusinessResponse)
                {
                    return FinishFavoriteScan(requestId, page, "收藏");
                }

                List<XhsFavoriteCandidate> firstSnapshot;
                lock (_favoriteScanLock) firstSnapshot = _favoriteScanCandidates.ToList();
                FavoriteScanProgress?.Invoke(requestId, firstSnapshot);

                int idleLimit = 3;
                int idleRounds = 0;
                int emptyPageGrace = 0;   // 空页只宽限一轮：页面可能先回预取空响应，真实分页随后到达。
                while (page.HasMore && !_favoriteScanCancelled && !_riskControlled && idleRounds < idleLimit)
                {
                    int beforeCount;
                    TaskCompletionSource<FavoriteEvidence> nextWaiter = NewWaiter<FavoriteEvidence>();
                    lock (_favoriteScanLock)
                    {
                        beforeCount = _favoriteScanCandidates.Count;
                        if (_favoriteLastPage != null && !_favoriteLastPage.IsEmptyPage) break;
                        _favoriteScanWaiter = nextWaiter;
                    }
                    string scrollState = await ScrollFavoritePageAsync();
                    Trace.LogAlways("xhs-scan op=" + requestId + " event=scroll before=" + beforeCount + " state=" + scrollState);
                    FavoriteEvidence nextPage = await WaitForResponseAsync(nextWaiter.Task, 5000);
                    if (nextPage != null)
                    {
                        page = nextPage;
                        if (page.IsRiskControlled || page.IsAnonymous || !page.IsAuthenticatedBusinessResponse)
                        {
                            break;
                        }
                    }
                    List<XhsFavoriteCandidate> domPage = await ReadFavoriteNotesFromDomAsync(requestId, true);
                    MergeFavoriteCandidates(domPage);
                    int afterCount;
                    lock (_favoriteScanLock) afterCount = _favoriteScanCandidates.Count;
                    Trace.LogAlways("xhs-scan op=" + requestId + " event=round_end response="
                        + (nextPage != null) + " count=" + afterCount + " dom=" + domPage.Count);
                    if (afterCount > beforeCount)
                    {
                        idleRounds = 0;
                        List<XhsFavoriteCandidate> snapshot;
                        lock (_favoriteScanLock) snapshot = _favoriteScanCandidates.ToList();
                        FavoriteScanProgress?.Invoke(requestId, snapshot);
                    }
                    else
                    {
                        idleRounds++;
                    }
                    if (nextPage == null && emptyPageGrace > 0) break;
                    if (nextPage != null && !page.HasMore)
                    {
                        if (!nextPage.IsEmptyPage || emptyPageGrace > 0) break;
                        emptyPageGrace++;
                        // while 以 HasMore 为条件：宽限轮先续上待确认状态，真实分页到达会覆盖它。
                        page = new FavoriteEvidence { IsAuthenticatedBusinessResponse = true, HasMore = true };
                    }
                }

                return FinishFavoriteScan(requestId, page, "收藏");
            }
            finally
            {
                _userMeWaiter = null;
                lock (_favoriteScanLock)
                {
                    _favoriteScanActive = false;
                    _favoriteScanIsAlbum = false;
                    _favoriteScanWaiter = null;
                    if (string.Equals(_favoriteScanRequestId, requestId, StringComparison.Ordinal))
                    {
                        _favoriteScanRequestId = null;
                    }
                }
                _checkGate.Release();
            }
        }

        private XhsSessionResult FinishFavoriteScan(string requestId, FavoriteEvidence page, string label)
        {
            List<XhsFavoriteCandidate> candidates;
            string reason;
            lock (_favoriteScanLock)
            {
                candidates = _favoriteScanCandidates.ToList();
                reason = _favoriteScanCancelled ? "cancelled"
                    : _riskControlled || page?.IsRiskControlled == true ? "platform_limit"
                    : page?.IsAnonymous == true ? "login_required"
                    : _favoriteLastPage != null ? "last_page"
                    : page == null || page.HasMore ? "incomplete"
                    : "invalid_response";
                _favoriteScanActive = false;
            }
            Trace.LogAlways("xhs-scan op=" + requestId + " event=stop reason=" + reason + " count=" + candidates.Count);
            bool complete = reason == "last_page";
            string message = complete ? "已读取" : reason == "cancelled" ? "读取已取消"
                : reason == "platform_limit" ? "读取受到平台限制" : reason == "login_required" ? "登录状态失效"
                : reason == "invalid_response" ? "分页格式无法确认" : "分页未完整读取";
            return new XhsSessionResult(complete ? "CONNECTED" : "PARTIAL", "小红书" + label + message,
                _browserProfile, false, candidates);
        }

        private const string NoteDetailScript = @"(function(expectedId){
  var path = location.pathname || '';
  var exploreMatch = /^\/explore\/([A-Za-z0-9_-]{1,100})\/?$/.exec(path);
  var profileMatch = /^\/user\/profile\/[A-Za-z0-9_-]{1,100}\/([A-Za-z0-9_-]{1,100})\/?$/.exec(path);
  var pathType = exploreMatch ? 'explore' : profileMatch ? 'profile' : 'other';
  var pathId = exploreMatch ? decodeURIComponent(exploreMatch[1])
    : profileMatch ? decodeURIComponent(profileMatch[1]) : '';
  var targetId = pathId || String(expectedId || '');
  var matchedId = '';
  var state = window.__INITIAL_STATE__ || {};
  var note = null;
  var map = (state.note && state.note.noteDetailMap) || null;
  if (map) {
    var keys = Object.keys(map);
    for (var i = 0; i < keys.length; i++) {
      var entry = map[keys[i]];
      if (!entry || !entry.note) continue;
      var entryId = String((entry.note.noteId || entry.note.id || keys[i]) || '');
      if (!targetId || entryId !== targetId) continue;
      if (entry.note.title || entry.note.desc || entry.note.imageList) {
        note = entry.note;
        matchedId = entryId;
        break;
      }
    }
  }
  function txt(sel) { var n = document.querySelector(sel); return n ? (n.textContent || '').trim() : ''; }
  var title = (note && note.title) || txt('#detail-title');
  var desc = (note && note.desc) || txt('#detail-desc');
  var author = (note && note.user && (note.user.nickname || note.user.nickName)) || '';
  var images = [];
  if (note && note.imageList) {
    for (var j = 0; j < note.imageList.length; j++) {
      var img = note.imageList[j] || {};
      var u = img.urlDefault || img.urlPre || img.url || '';
      if (u) images.push(u);
    }
  }
  if (!images.length) {
    var nodes = document.querySelectorAll('.swiper-slide img, .note-slider img, .media-container img');
    for (var k = 0; k < nodes.length; k++) {
      var src = nodes[k].currentSrc || nodes[k].src || '';
      if (src && src.indexOf('data:') !== 0 && images.indexOf(src) < 0) images.push(src);
    }
  }
  var video = '';
  if (note && note.video && note.video.media && note.video.media.stream) {
    var stream = note.video.media.stream;
    var groups = ['h264', 'h265', 'av1'];
    for (var g = 0; g < groups.length && !video; g++) {
      var list = stream[groups[g]];
      if (list && list.length) video = list[0].masterUrl || (list[0].backupUrls && list[0].backupUrls[0]) || '';
    }
  }
  if (!video) { var tag = document.querySelector('video'); if (tag) video = tag.currentSrc || tag.src || ''; }
  var id = (note && (note.noteId || note.id)) || matchedId || pathId || '';
  return JSON.stringify({id: id, title: title, text: desc, author: author, images: images, video: video});
})(/*TARGET_ID*/)";

        private const string FavoriteNoteActionScript = @"(function(targetId, reset){
  var cards = Array.from(document.querySelectorAll('section.note-item, div.note-item'));
  function identityFor(anchor) {
    try {
      var url = new URL(anchor.href, location.href);
      if (url.hostname.toLowerCase() !== 'www.xiaohongshu.com') return null;
      var match = /^\/explore\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      if (match) return {id:decodeURIComponent(match[1]), routeType:'explore'};
      match = /^\/user\/profile\/[A-Za-z0-9_-]{1,100}\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      return match ? {id:decodeURIComponent(match[1]), routeType:'profile'} : null;
    } catch (e) { return null; }
  }
  function visible(anchor) {
    var rect = anchor.getBoundingClientRect();
    var style = getComputedStyle(anchor);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden' && style.opacity !== '0';
  }
  function targetLink(card) {
    var matches = Array.from(card.querySelectorAll('a[href*=""/explore/""], a[href*=""/user/profile/""]'))
      .map(function(anchor){ return {anchor:anchor, identity:identityFor(anchor)}; })
      .filter(function(item){ return item.identity && item.identity.id === targetId && visible(item.anchor); });
    return matches.find(function(item){ return item.identity.routeType === 'profile'; }) || matches[0] || null;
  }
  var matched = null;
  var found = cards.find(function(card){
    var item = targetLink(card);
    matched = item && item.identity;
    return !!item;
  });
  if (found) {
    found.scrollIntoView({block:'center'});
    return JSON.stringify({found:true, moved:true, routeType:matched.routeType, noteId:matched.id});
  }
  var doc = document.scrollingElement || document.documentElement;
  var scroller = doc;
  var last = cards[cards.length - 1];
  for (var parent = last && last.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    if (parent.clientHeight >= 120 && parent.scrollHeight - parent.clientHeight >= 30) {
      scroller = parent;
      break;
    }
  }
  var before = scroller.scrollTop || 0;
  var maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  var next = reset ? 0 : Math.min(maxTop, before + Math.max(240, Math.round(scroller.clientHeight * 0.75)));
  if (scroller === doc) window.scrollTo(0, next);
  else scroller.scrollTop = next;
  return JSON.stringify({found:false, moved:Math.abs((scroller.scrollTop || 0) - before) > 2, items:cards.length});
})(/*TARGET_ID*/, /*RESET*/)";

        private const string ClickFavoriteNoteScript = @"(function(targetId){
  function identityFor(anchor) {
    try {
      var url = new URL(anchor.href, location.href);
      if (url.hostname.toLowerCase() !== 'www.xiaohongshu.com') return null;
      var match = /^\/explore\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      if (match) return {id:decodeURIComponent(match[1]), routeType:'explore'};
      match = /^\/user\/profile\/[A-Za-z0-9_-]{1,100}\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      return match ? {id:decodeURIComponent(match[1]), routeType:'profile'} : null;
    } catch (e) { return null; }
  }
  function visible(anchor) {
    var rect = anchor.getBoundingClientRect();
    var style = getComputedStyle(anchor);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden' && style.opacity !== '0';
  }
  function targetLink(card) {
    var matches = Array.from(card.querySelectorAll('a[href*=""/explore/""], a[href*=""/user/profile/""]'))
      .map(function(anchor){ return {anchor:anchor, identity:identityFor(anchor)}; })
      .filter(function(item){ return item.identity && item.identity.id === targetId && visible(item.anchor); });
    return matches.find(function(item){ return item.identity.routeType === 'profile'; }) || matches[0] || null;
  }
  var cards = Array.from(document.querySelectorAll('section.note-item, div.note-item'));
  var matched = null;
  var card = cards.find(function(node){
    var item = targetLink(node);
    matched = item && item.identity;
    return !!item;
  });
  var item = card && targetLink(card);
  var link = item && item.anchor;
  matched = item && item.identity;
  if (!link || !matched) return JSON.stringify({clicked:false});
  link.click();
  return JSON.stringify({clicked:true, routeType:matched.routeType, noteId:matched.id});
})(/*TARGET_ID*/)";

        private const string CaptureFavoriteListStateScript = @"(function(){
  var scrolls = Array.from(document.querySelectorAll('div, main, section, ul'))
    .filter(function(node){return node.clientHeight >= 120 && node.scrollHeight - node.clientHeight >= 30;})
    .map(function(node){return node.scrollTop || 0;});
  var doc = document.scrollingElement || document.documentElement;
  return JSON.stringify({
    x:window.scrollX || 0,
    y:window.scrollY || 0,
    documentHeight:doc.scrollHeight || 0,
    cardCount:document.querySelectorAll('section.note-item, div.note-item').length,
    scrolls:scrolls
  });
})()";

        private const string RestoreFavoriteListStateScript = @"(function(state){
  var nodes = Array.from(document.querySelectorAll('div, main, section, ul'))
    .filter(function(node){return node.clientHeight >= 120 && node.scrollHeight - node.clientHeight >= 30;});
  (state.scrolls || []).forEach(function(top, index){if(nodes[index]) nodes[index].scrollTop = top;});
  window.scrollTo(Number(state.x) || 0, Number(state.y) || 0);
  return true;
})(/*STATE*/)";

        private const string FavoriteNoteDetailVisibleScript = @"(function(){
  function visible(node){
    if (!node) return false;
    var rect = node.getBoundingClientRect();
    var style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  }
  var promptSelector = '[role=dialog],[aria-modal=true],[class*=modal],[class*=Modal],[class*=qr],[class*=Qr],[class*=QR],[id*=qr],[id*=Qr],[id*=QR],[class*=login],[class*=Login]';
  var phoneQrPrompt = Array.prototype.some.call(document.querySelectorAll(promptSelector), function(node){
    if (!visible(node)) return false;
    var text = (node.innerText || node.textContent || '').replace(/\s/g, '');
    return !/扫码登录|登录后查看/.test(text)
      && (/\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b/i.test(text)
        || (/手机/.test(text) && /扫码|二维码|扫描|查看/.test(text)));
  });
  var path = location.pathname || '';
  var exploreMatch = /^\/explore\/([A-Za-z0-9_-]{1,100})\/?$/.exec(path);
  var profileMatch = /^\/user\/profile\/[A-Za-z0-9_-]{1,100}\/([A-Za-z0-9_-]{1,100})\/?$/.exec(path);
  var routeType = exploreMatch ? 'explore' : profileMatch ? 'profile' : 'other';
  var routeId = exploreMatch ? decodeURIComponent(exploreMatch[1])
    : profileMatch ? decodeURIComponent(profileMatch[1]) : '';
  var titleVisible = visible(document.querySelector('#detail-title'));
  var bodyVisible = visible(document.querySelector('#detail-desc'));
  return {routeType:routeType, routeId:routeId, titleVisible:titleVisible, bodyVisible:bodyVisible,
    visible:titleVisible || bodyVisible, phoneQrPrompt:phoneQrPrompt};
})()";

        private const string CloseFavoriteNoteDetailScript = @"(function(){
  var detail = document.querySelector('#detail-title, #detail-desc');
  if (!detail) return false;
  var root = detail.closest('[role=dialog],[aria-modal=true]');
  if (!root) {
    for (var parent = detail.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (/detail|modal|overlay/i.test(String(parent.className || ''))) { root = parent; break; }
    }
  }
  var buttons = root ? Array.from(root.querySelectorAll('button,[role=button]')) : [];
  var close = buttons.find(function(button){
    return /close|关闭/i.test((button.getAttribute('aria-label') || '') + ' ' + String(button.className || ''));
  });
  if (close) close.click();
  else {
    document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true}));
  }
  return true;
})()";

        private static bool TryGetXhsNoteRoute(Uri target, out string routeType, out string noteId)
        {
            routeType = "other";
            noteId = null;
            if (target == null || !string.Equals(target.Host, "www.xiaohongshu.com", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            string path = target.AbsolutePath;
            if (path.EndsWith("/", StringComparison.Ordinal)) path = path.Substring(0, path.Length - 1);
            if (!path.StartsWith("/", StringComparison.Ordinal)) return false;
            string[] segments = path.Substring(1).Split('/');
            if (segments.Length == 2 && string.Equals(segments[0], "explore", StringComparison.OrdinalIgnoreCase))
            {
                routeType = "explore";
                noteId = Uri.UnescapeDataString(segments[1]);
            }
            else if (segments.Length == 4
                && string.Equals(segments[0], "user", StringComparison.OrdinalIgnoreCase)
                && string.Equals(segments[1], "profile", StringComparison.OrdinalIgnoreCase)
                && Trace.XhsId(Uri.UnescapeDataString(segments[2])) != "-")
            {
                routeType = "profile";
                noteId = Uri.UnescapeDataString(segments[3]);
            }
            else
            {
                return false;
            }

            if (Trace.XhsId(noteId) == "-")
            {
                routeType = "other";
                noteId = null;
                return false;
            }
            return true;
        }

        public async Task<XhsSessionResult> ReadNoteAsync(string operationId, string url, string scope, string albumId)
        {
            Uri target;
            string routeType;
            string noteId;
            if (!Uri.TryCreate(url, UriKind.Absolute, out target)
                || !TryGetXhsNoteRoute(target, out routeType, out noteId))
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书笔记链接无法识别");
            }
            if (string.IsNullOrWhiteSpace(noteId) || (scope != "notes" && scope != "album"))
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书收藏范围无法确认");
            }
            string trace = "xhs-note op=" + operationId;
            Trace.LogAlways(trace + " event=start scope=" + scope);
            await _checkGate.WaitAsync();
            try
            {
                await InitializeAsync();
                _riskControlled = false;
                string collectionUrl;
                int candidateIndex;
                bool resetToStart;
                lock (_favoriteScanLock)
                {
                    bool sameScope = string.Equals(scope, _favoriteScanScope, StringComparison.Ordinal)
                        && string.Equals(albumId, _favoriteScanAlbumId, StringComparison.Ordinal);
                    if (_favoriteScanActive || !sameScope || !_favoriteScanIds.Contains(noteId))
                    {
                        Trace.LogAlways(trace + " event=stop reason=scope_mismatch");
                        return new XhsSessionResult("REAUTH_REQUIRED", "小红书笔记不属于当前收藏范围");
                    }
                    collectionUrl = _favoriteScanCollectionUrl;
                    candidateIndex = _favoriteScanCandidates.FindIndex(
                        candidate => string.Equals(candidate.Id, noteId, StringComparison.Ordinal));
                    resetToStart = !string.Equals(scope, _favoriteReadScope, StringComparison.Ordinal)
                        || !string.Equals(albumId, _favoriteReadAlbumId, StringComparison.Ordinal)
                        || _favoriteReadCandidateIndex < 0
                        || candidateIndex <= _favoriteReadCandidateIndex;
                }
                if (string.IsNullOrWhiteSpace(collectionUrl) || candidateIndex < 0)
                {
                    Trace.LogAlways(trace + " event=stop reason=collection_missing");
                    return new XhsSessionResult("REAUTH_REQUIRED", "小红书收藏范围已失效，请重新读取");
                }
                if (!await EnsureFavoriteCollectionAsync(scope, collectionUrl))
                {
                    Trace.LogAlways(trace + " event=stop reason=collection_unavailable");
                    return new XhsSessionResult("REAUTH_REQUIRED", "小红书收藏列表未能打开");
                }

                string originalListState = await CaptureFavoriteListStateAsync();
                string listState = await OpenFavoriteNoteAsync(noteId, resetToStart, trace);
                Trace.LogAlways(trace + " event=open method=native_card clicked=" + !string.IsNullOrWhiteSpace(listState));
                if (string.IsNullOrWhiteSpace(listState))
                {
                    lock (_favoriteScanLock) _favoriteReadCandidateIndex = -1;
                    bool listRestored = await RestoreFavoriteListAsync(scope, collectionUrl, originalListState);
                    Trace.LogAlways(trace + " event=restore ok=" + listRestored);
                    if (!listRestored)
                    {
                        Trace.LogAlways(trace + " event=stop reason=card_not_found collection_restored=False");
                        return new XhsSessionResult("REAUTH_REQUIRED", "当前收藏列表中未找到笔记卡片；收藏列表恢复失败",
                            _browserProfile, collectionRestored: listRestored);
                    }
                    Trace.LogAlways(trace + " event=stop reason=card_not_found collection_restored=True");
                    return new XhsSessionResult("REAUTH_REQUIRED", "当前收藏列表中未找到该笔记卡片",
                        _browserProfile, collectionRestored: listRestored);
                }
                XhsNoteDetail note = null;
                string detailObservation = "detail_not_observed";
                for (int attempt = 0; attempt < 10 && note == null; attempt++)
                {
                    await Task.Delay(600);
                    (XhsNoteDetail Note, string Observation) read = await ReadNoteFromPageAsync(noteId, trace);
                    note = read.Note;
                    detailObservation = read.Observation;
                    if (detailObservation == "phone_qr_prompt") break;
                }
                bool restored = await RestoreFavoriteListAsync(scope, collectionUrl, listState);
                Trace.LogAlways(trace + " event=restore ok=" + restored);
                if (!restored)
                {
                    lock (_favoriteScanLock) _favoriteReadCandidateIndex = -1;
                }
                if (note == null)
                {
                    string message = detailObservation == "phone_qr_prompt"
                        ? "小红书提示：请打开小红书App扫码查看"
                        : "没有读到目标笔记正文";
                    if (!restored) message += "；收藏列表恢复失败";
                    Trace.LogAlways(trace + " event=stop reason=" + detailObservation
                        + " collection_restored=" + restored);
                    return new XhsSessionResult("REAUTH_REQUIRED", message, _browserProfile,
                        collectionRestored: restored);
                }
                if (restored)
                {
                    lock (_favoriteScanLock)
                    {
                        _favoriteReadScope = scope;
                        _favoriteReadAlbumId = albumId;
                        _favoriteReadCandidateIndex = candidateIndex;
                    }
                }
                string successMessage = restored
                    ? "小红书笔记已读取"
                    : "小红书笔记已读取，收藏列表恢复失败";
                return new XhsSessionResult("CONNECTED", successMessage, _browserProfile,
                    note: note, collectionRestored: restored);
            }
            finally
            {
                _checkGate.Release();
            }
        }

        private async Task<bool> EnsureFavoriteCollectionAsync(string scope, string collectionUrl, bool force = false)
        {
            if (!force && IsExpectedFavoriteCollectionPage(scope, collectionUrl)) return true;
            if (scope == "notes")
            {
                return await NavigateAndWaitAsync(collectionUrl)
                    && IsExpectedFavoriteCollectionPage(scope, collectionUrl);
            }
            if (scope != "album") return false;

            string directoryUrl;
            lock (_favoriteScanLock) directoryUrl = _favoriteDirectoryUrl;
            Uri album;
            if (string.IsNullOrWhiteSpace(directoryUrl)
                || !Uri.TryCreate(collectionUrl, UriKind.Absolute, out album)
                || !IsXiaohongshuDomain(album.Host))
            {
                return false;
            }
            if (!IsExpectedFavoriteDirectoryPage(directoryUrl)
                && !await NavigateAndWaitAsync(directoryUrl))
            {
                return false;
            }
            return await ClickFavoriteAlbumLinkAsync(collectionUrl, album.AbsolutePath, null)
                && IsExpectedFavoriteCollectionPage(scope, collectionUrl);
        }

        private bool IsExpectedFavoriteCollectionPage(string scope, string collectionUrl)
        {
            Uri expected;
            if (!Uri.TryCreate(collectionUrl, UriKind.Absolute, out expected)
                || !IsXiaohongshuDomain(expected.Host)) return false;
            if (scope == "notes")
            {
                const string profilePrefix = "/user/profile/";
                if (!expected.AbsolutePath.StartsWith(profilePrefix, StringComparison.OrdinalIgnoreCase)) return false;
                string userId = Uri.UnescapeDataString(expected.AbsolutePath.Substring(profilePrefix.Length)).TrimEnd('/');
                return !string.IsNullOrWhiteSpace(userId) && !userId.Contains("/") && IsExpectedFavoritePage(userId);
            }
            Uri current;
            return scope == "album"
                && Uri.TryCreate(_core.Source, UriKind.Absolute, out current)
                && IsXiaohongshuDomain(current.Host)
                && string.Equals(
                    Uri.UnescapeDataString(current.AbsolutePath).TrimEnd('/'),
                    Uri.UnescapeDataString(expected.AbsolutePath).TrimEnd('/'),
                    StringComparison.OrdinalIgnoreCase);
        }

        private bool IsExpectedFavoriteDirectoryPage(string directoryUrl)
        {
            Uri expected;
            Uri current;
            return Uri.TryCreate(directoryUrl, UriKind.Absolute, out expected)
                && Uri.TryCreate(_core.Source, UriKind.Absolute, out current)
                && IsXiaohongshuDomain(current.Host)
                && string.Equals(current.AbsolutePath, expected.AbsolutePath, StringComparison.OrdinalIgnoreCase)
                && string.Equals(current.Query, expected.Query, StringComparison.Ordinal);
        }

        private async Task<string> OpenFavoriteNoteAsync(string noteId, bool resetToStart, string trace)
        {
            int idleRounds = 0;
            for (int attempt = 0; attempt < 40; attempt++)
            {
                string script = FavoriteNoteActionScript
                    .Replace("/*TARGET_ID*/", JsonSerializer.Serialize(noteId))
                    .Replace("/*RESET*/", resetToStart && attempt == 0 ? "true" : "false");
                string encoded = await _core.ExecuteScriptAsync(script);
                string json = JsonSerializer.Deserialize<string>(encoded);
                using (JsonDocument document = JsonDocument.Parse(json))
                {
                    JsonElement root = document.RootElement;
                    if (root.GetProperty("found").GetBoolean())
                    {
                        string listState = await CaptureFavoriteListStateAsync();
                        if (string.IsNullOrWhiteSpace(listState)) return null;
                        string clickScript = ClickFavoriteNoteScript.Replace("/*TARGET_ID*/", JsonSerializer.Serialize(noteId));
                        string clickEncoded = await _core.ExecuteScriptAsync(clickScript);
                        string clickJson = JsonSerializer.Deserialize<string>(clickEncoded);
                        bool clicked = false;
                        string pathType = "other";
                        string actualNoteId = null;
                        using (JsonDocument clickDocument = JsonDocument.Parse(clickJson))
                        {
                            JsonElement clickResult = clickDocument.RootElement;
                            clicked = clickResult.TryGetProperty("clicked", out JsonElement clickedValue)
                                && clickedValue.ValueKind == JsonValueKind.True;
                            if (clickResult.TryGetProperty("routeType", out JsonElement routeValue)
                                && routeValue.ValueKind == JsonValueKind.String)
                                pathType = routeValue.GetString();
                            if (clickResult.TryGetProperty("noteId", out JsonElement idValue)
                                && idValue.ValueKind == JsonValueKind.String)
                                actualNoteId = idValue.GetString();
                        }
                        bool supportedPath = pathType == "explore" || pathType == "profile";
                        bool matchedNote = string.Equals(actualNoteId, noteId, StringComparison.Ordinal);
                        Trace.LogAlways(trace + " event=card_click path_type="
                            + (supportedPath ? pathType : "other") + " note_id=" + Trace.XhsId(actualNoteId));
                        return clicked && supportedPath && matchedNote ? listState : null;
                    }
                    bool moved = root.GetProperty("moved").GetBoolean();
                    idleRounds = moved ? 0 : idleRounds + 1;
                }
                if (idleRounds >= 3) return null;
                await Task.Delay(idleRounds == 0 ? 500 : 1000);
            }
            return null;
        }

        private async Task<string> CaptureFavoriteListStateAsync()
        {
            string encoded = await _core.ExecuteScriptAsync(CaptureFavoriteListStateScript);
            return JsonSerializer.Deserialize<string>(encoded);
        }

        private async Task<bool> RestoreFavoriteListAsync(string scope, string collectionUrl, string stateJson)
        {
            if (await IsFavoriteNoteDetailVisibleAsync())
            {
                await _core.ExecuteScriptAsync(CloseFavoriteNoteDetailScript);
                await Task.Delay(350);
            }
            if (!IsExpectedFavoriteCollectionPage(scope, collectionUrl)
                || await IsFavoriteNoteDetailVisibleAsync())
            {
                if (_core.CanGoBack)
                {
                    try { _core.GoBack(); } catch { }
                    DateTime deadline = DateTime.UtcNow.AddMilliseconds(CheckTimeoutMilliseconds);
                    while (DateTime.UtcNow < deadline)
                    {
                        if (IsExpectedFavoriteCollectionPage(scope, collectionUrl)
                            && !await IsFavoriteNoteDetailVisibleAsync()) break;
                        await Task.Delay(250);
                    }
                }
            }
            if (!IsExpectedFavoriteCollectionPage(scope, collectionUrl)
                || await IsFavoriteNoteDetailVisibleAsync())
            {
                if (!await EnsureFavoriteCollectionAsync(scope, collectionUrl, true)) return false;
            }
            if (!IsExpectedFavoriteCollectionPage(scope, collectionUrl)
                || await IsFavoriteNoteDetailVisibleAsync()) return false;
            return await RestoreFavoriteListStateAsync(stateJson);
        }

        private async Task<bool> IsFavoriteNoteDetailVisibleAsync()
        {
            string encoded = await _core.ExecuteScriptAsync(FavoriteNoteDetailVisibleScript);
            using (JsonDocument document = JsonDocument.Parse(encoded))
            {
                JsonElement root = document.RootElement;
                return root.ValueKind == JsonValueKind.Object
                    && root.TryGetProperty("visible", out JsonElement visible)
                    && visible.ValueKind == JsonValueKind.True;
            }
        }

        private async Task<bool> RestoreFavoriteListStateAsync(string stateJson)
        {
            string script = RestoreFavoriteListStateScript.Replace("/*STATE*/", stateJson);
            string previous = null;
            int idleRounds = 0;
            for (int attempt = 0; attempt < 40; attempt++)
            {
                await _core.ExecuteScriptAsync(script);
                await Task.Delay(400);
                string current = await CaptureFavoriteListStateAsync();
                if (FavoriteListStateMatches(stateJson, current)) return true;
                idleRounds = string.Equals(previous, current, StringComparison.Ordinal) ? idleRounds + 1 : 0;
                if (idleRounds >= 5) return false;
                previous = current;
            }
            return false;
        }

        private static bool FavoriteListStateMatches(string expectedJson, string actualJson)
        {
            using (JsonDocument expected = JsonDocument.Parse(expectedJson))
            using (JsonDocument actual = JsonDocument.Parse(actualJson))
            {
                JsonElement wanted = expected.RootElement;
                JsonElement found = actual.RootElement;
                if (Math.Abs(found.GetProperty("x").GetDouble() - wanted.GetProperty("x").GetDouble()) > 2
                    || Math.Abs(found.GetProperty("y").GetDouble() - wanted.GetProperty("y").GetDouble()) > 2
                    || found.GetProperty("documentHeight").GetInt32() < wanted.GetProperty("documentHeight").GetInt32()
                    || found.GetProperty("cardCount").GetInt32() < wanted.GetProperty("cardCount").GetInt32())
                {
                    return false;
                }
                JsonElement wantedScrolls = wanted.GetProperty("scrolls");
                JsonElement foundScrolls = found.GetProperty("scrolls");
                if (foundScrolls.GetArrayLength() < wantedScrolls.GetArrayLength()) return false;
                for (int index = 0; index < wantedScrolls.GetArrayLength(); index++)
                {
                    if (Math.Abs(foundScrolls[index].GetDouble() - wantedScrolls[index].GetDouble()) > 2) return false;
                }
                return true;
            }
        }

        private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(string noteId, string trace)
        {
            try
            {
                string probeEncoded = await _core.ExecuteScriptAsync(FavoriteNoteDetailVisibleScript);
                string routeType = "other";
                string routeId = null;
                bool titleVisible = false;
                bool bodyVisible = false;
                bool detailVisible = false;
                bool phoneQrPrompt = false;
                using (JsonDocument probe = JsonDocument.Parse(probeEncoded))
                {
                    JsonElement root = probe.RootElement;
                    if (root.ValueKind == JsonValueKind.Object)
                    {
                        if (root.TryGetProperty("routeType", out JsonElement route)
                            && route.ValueKind == JsonValueKind.String
                            && (route.GetString() == "explore" || route.GetString() == "profile"))
                            routeType = route.GetString();
                        if (root.TryGetProperty("routeId", out JsonElement routeNoteId)
                            && routeNoteId.ValueKind == JsonValueKind.String)
                            routeId = routeNoteId.GetString();
                        titleVisible = root.TryGetProperty("titleVisible", out JsonElement title)
                            && title.ValueKind == JsonValueKind.True;
                        bodyVisible = root.TryGetProperty("bodyVisible", out JsonElement body)
                            && body.ValueKind == JsonValueKind.True;
                        detailVisible = root.TryGetProperty("visible", out JsonElement visible)
                            && visible.ValueKind == JsonValueKind.True;
                        phoneQrPrompt = root.TryGetProperty("phoneQrPrompt", out JsonElement prompt)
                            && prompt.ValueKind == JsonValueKind.True;
                    }
                }
                Trace.LogAlways(trace + " event=probe route=" + routeType
                    + " note_id=" + Trace.XhsId(routeId)
                    + " title_visible=" + titleVisible + " body_visible=" + bodyVisible
                    + " phone_qr_prompt=" + phoneQrPrompt);
                if (phoneQrPrompt)
                {
                    Trace.LogAlways(trace + " event=detail_observation result=phone_qr_prompt");
                    return (null, "phone_qr_prompt");
                }
                if (!detailVisible)
                {
                    Trace.LogAlways(trace + " event=detail_observation result=not_observed");
                    return (null, "detail_not_observed");
                }
                Trace.LogAlways(trace + " event=detail_observation result=visible");
                string script = NoteDetailScript.Replace("/*TARGET_ID*/", JsonSerializer.Serialize(noteId));
                string encoded = await _core.ExecuteScriptAsync(script);
                string json; 
                using (JsonDocument outer = JsonDocument.Parse(encoded))
                {
                    json = outer.RootElement.ValueKind == JsonValueKind.String
                        ? outer.RootElement.GetString() : null;
                }
                if (string.IsNullOrWhiteSpace(json)) return (null, "detail_error");
                using (JsonDocument document = JsonDocument.Parse(json))
                {
                    JsonElement root = document.RootElement;
                    string id = FirstString(root, "id").Trim();
                    string text = FirstString(root, "text").Trim();
                    bool idMatches = !string.IsNullOrWhiteSpace(id)
                        && string.Equals(id, noteId, StringComparison.Ordinal);
                    bool bodyPresent = !string.IsNullOrWhiteSpace(text);
                    Trace.LogAlways(trace + " event=detail id_match=" + idMatches
                        + " body_present=" + bodyPresent);
                    if (!idMatches) return (null, "detail_visible");
                    string title = FirstString(root, "title").Trim();
                    if (!bodyPresent) return (null, "detail_visible");
                    string cover = string.Empty;
                    JsonElement images;
                    if (root.TryGetProperty("images", out images) && images.ValueKind == JsonValueKind.Array)
                    {
                        foreach (JsonElement image in images.EnumerateArray())
                        {
                            if (image.ValueKind != JsonValueKind.String) continue;
                            string candidate = NormalizeCoverUrl(image.GetString());
                            if (!string.IsNullOrWhiteSpace(candidate)) { cover = candidate; break; }
                        }
                    }
                    return (new XhsNoteDetail
                    {
                        NoteId = id,
                        Url = "https://www.xiaohongshu.com/explore/" + Uri.EscapeDataString(id),
                        Title = title,
                        Author = FirstString(root, "author").Trim(),
                        Text = text,
                        ThumbnailUrl = cover,
                        VideoUrl = FirstString(root, "video").Trim(),
                    }, "body_verified");
                }
            }
            catch (Exception error)
            {
                Trace.LogAlways(trace + " event=detail_error type=" + error.GetType().Name);
                return (null, "detail_error");
            }
        }

        private const string FavoriteNoteDomScript = @"(function(){
  var nodes = Array.from(document.querySelectorAll('section.note-item, div.note-item'));
  var out = [];
  function visible(anchor) {
    var rect = anchor.getBoundingClientRect();
    var style = getComputedStyle(anchor);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden' && style.opacity !== '0';
  }
  function identityFor(anchor) {
    try {
      var url = new URL(anchor.href, location.href);
      if (url.hostname.toLowerCase() !== 'www.xiaohongshu.com') return null;
      var match = /^\/explore\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      if (match) return {id:decodeURIComponent(match[1]), routeType:'explore'};
      match = /^\/user\/profile\/[A-Za-z0-9_-]{1,100}\/([A-Za-z0-9_-]{1,100})\/?$/.exec(url.pathname);
      return match ? {id:decodeURIComponent(match[1]), routeType:'profile'} : null;
    } catch (e) { return null; }
  }
  nodes.forEach(function(node){
    var links = Array.from(node.querySelectorAll('a[href*=""/explore/""], a[href*=""/user/profile/""]'))
      .map(function(anchor){ return {anchor:anchor, identity:identityFor(anchor)}; })
      .filter(function(item){ return item.identity && visible(item.anchor); });
    if (!links.length) return;
    var firstId = links[0].identity.id;
    var selected = links.find(function(item){ return item.identity.id === firstId && item.identity.routeType === 'profile'; })
      || links[0];
    var anchor = selected.anchor;
    var href = anchor.getAttribute('href') || '';
    var identity = selected.identity;
    if (!identity) return;
    var titleNode = node.querySelector('.footer .title, .note-title, .title');
    var authorNode = node.querySelector('.author .name, .author-wrapper .name, .name');
    var imageNode = node.querySelector('img');
    out.push({
      id: identity.id,
      routeType: identity.routeType,
      href: href,
      title: titleNode ? (titleNode.textContent || '').trim() : '',
      author: authorNode ? (authorNode.textContent || '').trim() : '',
      cover: imageNode ? (imageNode.currentSrc || imageNode.src || imageNode.getAttribute('data-src') || '') : '',
      video: !!node.querySelector('video')
    });
  });
  return JSON.stringify(out);
})()";

        private const string FavoritePageProbeScript = @"(function(){
  function n(sel){ try { return document.querySelectorAll(sel).length; } catch (e) { return -1; } }
  var anchors = Array.from(document.querySelectorAll('a[href*=""/explore/""]')).slice(0, 3).map(function(a){ return a.getAttribute('href') || ''; });
  return JSON.stringify({
    href: location.href,
    items: n('section.note-item'),
    itemsAlt: n('div.note-item'),
    explore: n('a[href*=""/explore/""]'),
    board: n('a.board-card'),
    tabs: Array.from(document.querySelectorAll('div.reds-tab-item')).map(function(x){ return (x.textContent || '').trim(); }).slice(0, 6),
    sample: anchors
  });
})()";

        private const string ScrollNudgeScript = @"(function(){
  var doc = document.scrollingElement || document.documentElement;
  var maxY = Math.max(0, doc.scrollHeight - window.innerHeight);
  if (maxY - (window.scrollY || 0) < 40) { window.scrollTo(0, Math.max(0, maxY - 400)); }
  return 'ok';
})()";

        private const string ScrollFavoritePageScript = @"(function(){
  var moved = 0, deepest = 0;
  var nodes = document.querySelectorAll('div, main, section, ul');
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    if (el.clientHeight < 120) continue;
    if (el.scrollHeight - el.clientHeight < 30) continue;
    el.scrollTop = el.scrollHeight;
    moved++;
    if (el.scrollHeight > deepest) deepest = el.scrollHeight;
  }
  var doc = document.scrollingElement || document.documentElement;
  window.scrollTo(0, doc.scrollHeight);
  var cards = document.querySelectorAll('section.note-item, div.note-item');
  if (cards.length) { cards[cards.length - 1].scrollIntoView({block: 'end'}); }
  var text = document.body ? (document.body.innerText || '') : '';
  return JSON.stringify({
    moved: moved, deepest: deepest, y: Math.round(window.scrollY || 0),
    bodyH: doc.scrollHeight, items: document.querySelectorAll('section.note-item, div.note-item').length,
    more: text.indexOf('没有更多') >= 0 ? 'end' : (text.indexOf('加载更多') >= 0 ? 'button' : '-')
  });
})()";

        private async Task<string> ScrollFavoritePageAsync()
        {
            try
            {
                // 已贴底时先回退一段，再滚到底：同一位置重复 scrollTo 不产生滚动事件，加载器不会被唤醒。
                await _core.ExecuteScriptAsync(ScrollNudgeScript);
                await Task.Delay(150);
                string encoded = await _core.ExecuteScriptAsync(ScrollFavoritePageScript);
                using (JsonDocument outer = JsonDocument.Parse(encoded))
                {
                    return outer.RootElement.ValueKind == JsonValueKind.String
                        ? (outer.RootElement.GetString() ?? "-")
                        : outer.RootElement.GetRawText();
                }
            }
            catch (Exception error)
            {
                return "scroll-error " + error.GetType().Name;
            }
        }

        private async Task<List<XhsFavoriteCandidate>> ReadFavoriteNotesFromDomAsync(string requestId, bool scroll)
        {
            var found = new List<XhsFavoriteCandidate>();
            int attempts = scroll ? 1 : 3;
            for (int attempt = 0; attempt < attempts && !FavoriteScanCancelled(requestId); attempt++)
            {
                try
                {
                    if (scroll)
                    {
                        await ScrollFavoritePageAsync();
                        await Task.Delay(500);
                    }
                    string encoded = await _core.ExecuteScriptAsync(FavoriteNoteDomScript);
                    using (JsonDocument outer = JsonDocument.Parse(encoded))
                    {
                        string json = outer.RootElement.ValueKind == JsonValueKind.String
                            ? outer.RootElement.GetString() : null;
                        if (!string.IsNullOrWhiteSpace(json))
                        {
                            using (JsonDocument document = JsonDocument.Parse(json))
                            {
                                if (document.RootElement.ValueKind == JsonValueKind.Array)
                                {
                                    foreach (JsonElement item in document.RootElement.EnumerateArray())
                                    {
                                        string id = FirstString(item, "id");
                                        if (string.IsNullOrWhiteSpace(id)) continue;
                                        string href = FirstString(item, "href");
                                        string url = string.Empty;
                                        bool hasOriginalDomUrl = false;
                                        Uri resolved;
                                        if (Uri.TryCreate("https://www.xiaohongshu.com/", UriKind.Absolute, out Uri baseUri)
                                            && Uri.TryCreate(baseUri, href, out resolved)
                                            && TryGetXhsNoteRoute(resolved, out _, out string hrefNoteId)
                                            && string.Equals(hrefNoteId, id, StringComparison.Ordinal))
                                        {
                                            // 原样保留页面给出的 xsec_token / xsec_source：token 与 source 绑定，改写会被判失效。
                                            url = resolved.AbsoluteUri;
                                            hasOriginalDomUrl = true;
                                        }
                                        if (string.IsNullOrWhiteSpace(url))
                                        {
                                            url = "https://www.xiaohongshu.com/explore/" + Uri.EscapeDataString(id);
                                        }
                                        bool isVideo = item.TryGetProperty("video", out JsonElement video)
                                            && video.ValueKind == JsonValueKind.True;
                                        found.Add(new XhsFavoriteCandidate
                                        {
                                            CandidateId = "note:" + id,
                                            Id = id,
                                            Title = FirstString(item, "title"),
                                            Author = FirstString(item, "author"),
                                            Type = isVideo ? "video" : "normal",
                                            Url = url,
                                            ThumbnailUrl = NormalizeCoverUrl(FirstString(item, "cover")),
                                            HasOriginalDomUrl = hasOriginalDomUrl,
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
                catch (Exception error)
                {
                    Trace.LogAlways("xhs-scan op=" + requestId + " event=dom_error type=" + error.GetType().Name);
                }
                if (found.Count > 0) break;
                await Task.Delay(400);
            }
            return found;
        }

        private void MergeFavoriteCandidates(IReadOnlyList<XhsFavoriteCandidate> items)
        {
            if (items == null || items.Count == 0) return;
            lock (_favoriteScanLock)
            {
                MergeFavoriteCandidatesLocked(items);
            }
        }

        private void MergeFavoriteCandidatesLocked(IReadOnlyList<XhsFavoriteCandidate> items)
        {
            foreach (XhsFavoriteCandidate candidate in items)
            {
                if (string.IsNullOrWhiteSpace(candidate.Id)) continue;
                if (_favoriteScanIds.Add(candidate.Id))
                {
                    _favoriteScanCandidates.Add(candidate);
                    continue;
                }
                if (!candidate.HasOriginalDomUrl) continue;
                int existingIndex = _favoriteScanCandidates.FindIndex(
                    existing => string.Equals(existing.Id, candidate.Id, StringComparison.Ordinal));
                if (existingIndex >= 0 && !_favoriteScanCandidates[existingIndex].HasOriginalDomUrl)
                {
                    _favoriteScanCandidates[existingIndex] = candidate;
                }
            }
        }

        private async Task<string> ProbeFavoritePageAsync()
        {
            try
            {
                string encoded = await _core.ExecuteScriptAsync(FavoritePageProbeScript);
                using (JsonDocument outer = JsonDocument.Parse(encoded))
                {
                    return outer.RootElement.ValueKind == JsonValueKind.String
                        ? (outer.RootElement.GetString() ?? "-")
                        : outer.RootElement.GetRawText();
                }
            }
            catch (Exception error)
            {
                return "probe-error " + error.GetType().Name + ": " + error.Message;
            }
        }

        private async Task<XhsSessionResult> ScanFavoriteDirectoryAsync(string requestId, string userId)
        {
            string url = "https://www.xiaohongshu.com/user/profile/"
                + Uri.EscapeDataString(userId) + "?tab=fav&subTab=board";
            lock (_favoriteScanLock) _favoriteDirectoryUrl = url;
            if (!await NavigateAndWaitAsync(url))
            {
                return await RiskOrUnavailableAsync("小红书专辑目录未能加载");
            }
            if (FavoriteScanCancelled(requestId))
            {
                return new XhsSessionResult("PARTIAL", "小红书专辑目录读取已取消", _browserProfile);
            }

            AlbumDirectoryEvidence directory = await ReadFavoriteAlbumsAsync(requestId);
            lock (_favoriteScanLock)
            {
                _favoriteAlbumUrls.Clear();
                foreach (KeyValuePair<string, string> item in directory.Urls)
                {
                    _favoriteAlbumUrls[item.Key] = item.Value;
                }
            }
            if (FavoriteScanCancelled(requestId))
            {
                return new XhsSessionResult("PARTIAL", "小红书专辑目录读取已取消", _browserProfile, false, null, directory.Albums);
            }
            if (!directory.IsConfirmed)
            {
                return new XhsSessionResult("PARTIAL", "小红书专辑目录未能完整确认", _browserProfile, false, null, directory.Albums);
            }
            return new XhsSessionResult("CONNECTED", "小红书专辑目录已读取", _browserProfile, false, null, directory.Albums);
        }

        private async Task<AlbumDirectoryEvidence> ReadFavoriteAlbumsAsync(string requestId)
        {
            const string script = @"(function(){
  var tab = Array.from(document.querySelectorAll('div.reds-tab-item')).find(function(node){ return /专辑/.test(node.textContent || ''); });
  var cards = Array.from(document.querySelectorAll('a.board-card')).map(function(anchor){
    return {
      href: anchor.getAttribute('href') || '',
      title: (anchor.querySelector('.board-name .title') || {}).textContent || '',
      count: (anchor.querySelector('.desc .notes') || {}).textContent || ''
    };
  });
  return JSON.stringify({tab: tab ? tab.textContent || '' : '', cards: cards});
})()";
            DateTime deadline = DateTime.UtcNow.AddSeconds(20);
            int? expectedCount = null;
            var cards = new Dictionary<string, XhsFavoriteAlbum>(StringComparer.Ordinal);
            var orderedIds = new List<string>();
            var urls = new Dictionary<string, string>(StringComparer.Ordinal);
            while (DateTime.UtcNow < deadline && !FavoriteScanCancelled(requestId))
            {
                try
                {
                    string encoded = await _core.ExecuteScriptAsync(script);
                    using (JsonDocument outer = JsonDocument.Parse(encoded))
                    {
                        string json = outer.RootElement.ValueKind == JsonValueKind.String
                            ? outer.RootElement.GetString() : null;
                        if (!string.IsNullOrWhiteSpace(json))
                        {
                            using (JsonDocument document = JsonDocument.Parse(json))
                            {
                                JsonElement root = document.RootElement;
                                string tab = FirstString(root, "tab");
                                expectedCount = ParseAlbumCount(tab) ?? expectedCount;
                                JsonElement cardsElement;
                                if (expectedCount.HasValue
                                    && root.TryGetProperty("cards", out cardsElement)
                                    && cardsElement.ValueKind == JsonValueKind.Array)
                                {
                                    foreach (JsonElement card in cardsElement.EnumerateArray())
                                    {
                                        string href = FirstString(card, "href");
                                        string title = FirstString(card, "title").Trim();
                                        if (!TryResolveFavoriteAlbum(href, out string albumId, out string albumUrl)) continue;
                                        int? mediaCount = ParseTrailingCount(FirstString(card, "count"));
                                        cards[albumId] = new XhsFavoriteAlbum
                                        {
                                            AlbumId = albumId,
                                            Title = string.IsNullOrWhiteSpace(title) ? "未命名专辑" : title,
                                            MediaCount = mediaCount,
                                        };
                                        if (!orderedIds.Contains(albumId)) orderedIds.Add(albumId);
                                        urls[albumId] = albumUrl;
                                    }
                                    if (cards.Count == expectedCount.Value)
                                    {
                                        return new AlbumDirectoryEvidence
                                        {
                                            IsConfirmed = true,
                                            Albums = orderedIds.Select(id => cards[id]).ToList(),
                                            Urls = urls,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }
                catch
                {
                    // The WebView may still be rendering the selected favorites tab.
                }
                try { await _core.ExecuteScriptAsync("window.scrollTo(0, document.body.scrollHeight); true;"); }
                catch { }
                await Task.Delay(400);
            }
            return new AlbumDirectoryEvidence
            {
                Albums = orderedIds.Select(id => cards[id]).ToList(),
                Urls = urls,
            };
        }

        private async Task<XhsSessionResult> ScanFavoriteAlbumAsync(string requestId, string albumUrl)
        {
            Uri target;
            if (!Uri.TryCreate(albumUrl, UriKind.Absolute, out target)
                || target.Scheme != Uri.UriSchemeHttps
                || !string.Equals(target.Host, "www.xiaohongshu.com", StringComparison.OrdinalIgnoreCase)
                || !target.AbsolutePath.StartsWith("/board/", StringComparison.OrdinalIgnoreCase))
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书专辑入口已失效，请重新读取目录", _browserProfile);
            }

            lock (_favoriteScanLock)
            {
                _favoriteScanCandidates.Clear();
                _favoriteScanIds.Clear();
                _favoriteScanActive = true;
                _favoriteScanIsAlbum = true;
                _favoriteScanWaiter = NewWaiter<FavoriteEvidence>();
            }
            string directoryUrl;
            lock (_favoriteScanLock) directoryUrl = _favoriteDirectoryUrl;
            if (string.IsNullOrWhiteSpace(directoryUrl))
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书专辑目录已失效，请重新读取", _browserProfile);
            }
            Uri directory;
            Uri currentPage;
            if (!Uri.TryCreate(directoryUrl, UriKind.Absolute, out directory)
                || !Uri.TryCreate(_core.Source, UriKind.Absolute, out currentPage)
                || !string.Equals(currentPage.AbsolutePath, directory.AbsolutePath, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(currentPage.Query, directory.Query, StringComparison.Ordinal))
            {
                if (!await NavigateAndWaitAsync(directoryUrl))
                {
                    return await RiskOrUnavailableAsync("小红书专辑目录未能重新打开");
                }
            }
            if (!await ClickFavoriteAlbumLinkAsync(albumUrl, target.AbsolutePath, requestId))
            {
                if (FavoriteScanCancelled(requestId)) return FinishFavoriteScan(requestId, null, "专辑");
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书专辑入口未能打开，请重新读取目录", _browserProfile);
            }
            if (FavoriteScanCancelled(requestId))
            {
                return FinishFavoriteScan(requestId, null, "专辑");
            }
            Uri current;
            if (!Uri.TryCreate(_core.Source, UriKind.Absolute, out current)
                || !string.Equals(current.Host, target.Host, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(current.AbsolutePath, target.AbsolutePath, StringComparison.OrdinalIgnoreCase))
            {
                return new XhsSessionResult("REAUTH_REQUIRED", "小红书专辑页面发生跳转，内容暂时无法确认", _browserProfile);
            }

            TaskCompletionSource<FavoriteEvidence> waiter;
            lock (_favoriteScanLock) waiter = _favoriteScanWaiter;
            FavoriteEvidence page = await WaitForResponseAsync(waiter.Task);
            if (page == null || !page.IsAuthenticatedBusinessResponse || FavoriteScanCancelled(requestId))
            {
                return FinishFavoriteScan(requestId, page, "专辑");
            }

            List<XhsFavoriteCandidate> albumFirstSnapshot;
            lock (_favoriteScanLock) albumFirstSnapshot = _favoriteScanCandidates.ToList();
            FavoriteScanProgress?.Invoke(requestId, albumFirstSnapshot);

            int idleRounds = 0;
            while (page.HasMore && !FavoriteScanCancelled(requestId) && !_riskControlled)
            {
                int beforeCount;
                TaskCompletionSource<FavoriteEvidence> nextWaiter = NewWaiter<FavoriteEvidence>();
                lock (_favoriteScanLock)
                {
                    beforeCount = _favoriteScanCandidates.Count;
                    if (_favoriteLastPage != null) break;
                    _favoriteScanWaiter = nextWaiter;
                }
                Trace.LogAlways("xhs-scan op=" + requestId + " event=scroll before=" + beforeCount);
                await _core.ExecuteScriptAsync("window.scrollTo(0, document.body.scrollHeight); true;");
                FavoriteEvidence nextPage = await WaitForResponseAsync(nextWaiter.Task);
                Trace.LogAlways("xhs-scan op=" + requestId + " event=round_end response=" + (nextPage != null));
                if (nextPage == null)
                {
                    idleRounds++;
                    if (idleRounds >= 3) break;
                    continue;
                }
                page = nextPage;
                if (page.IsRiskControlled || page.IsAnonymous || !page.IsAuthenticatedBusinessResponse) break;
                int afterCount;
                lock (_favoriteScanLock) afterCount = _favoriteScanCandidates.Count;
                idleRounds = afterCount > beforeCount ? 0 : idleRounds + 1;
                if (afterCount > beforeCount)
                {
                    List<XhsFavoriteCandidate> albumSnapshot;
                    lock (_favoriteScanLock) albumSnapshot = _favoriteScanCandidates.ToList();
                    FavoriteScanProgress?.Invoke(requestId, albumSnapshot);
                }
                if (idleRounds >= 3 && page.HasMore) break;
            }

            return FinishFavoriteScan(requestId, page, "专辑");
        }

        private async Task<bool> ClickFavoriteAlbumLinkAsync(string albumUrl, string expectedPath, string requestId)
        {
            string href = JsonSerializer.Serialize(albumUrl);
            string clickScript = "(function(){var target=" + href
                + ";var link=Array.from(document.querySelectorAll('a.board-card')).find(function(anchor){return anchor.href===target;});"
                + "if(!link)return false;link.scrollIntoView({block:'center'});link.click();return true;})()";
            DateTime deadline = DateTime.UtcNow.AddSeconds(20);
            while (DateTime.UtcNow < deadline && (requestId == null || !FavoriteScanCancelled(requestId)))
            {
                string result = await _core.ExecuteScriptAsync(clickScript);
                if (string.Equals(result, "true", StringComparison.OrdinalIgnoreCase)) break;
                await Task.Delay(250);
            }
            while (DateTime.UtcNow < deadline && (requestId == null || !FavoriteScanCancelled(requestId)))
            {
                string encodedPath = await _core.ExecuteScriptAsync("location.pathname");
                try
                {
                    using (JsonDocument document = JsonDocument.Parse(encodedPath))
                    {
                        if (document.RootElement.ValueKind == JsonValueKind.String
                            && string.Equals(document.RootElement.GetString(), expectedPath, StringComparison.OrdinalIgnoreCase))
                        {
                            return true;
                        }
                    }
                }
                catch { }
                await Task.Delay(250);
            }
            return false;
        }

        private static bool TryResolveFavoriteAlbum(string href, out string albumId, out string albumUrl)
        {
            albumId = null;
            albumUrl = null;
            Uri baseUri = new Uri("https://www.xiaohongshu.com/");
            Uri resolved;
            if (!Uri.TryCreate(baseUri, href, out resolved)
                || resolved.Scheme != Uri.UriSchemeHttps
                || !string.Equals(resolved.Host, "www.xiaohongshu.com", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            string[] segments = resolved.AbsolutePath.Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
            if (segments.Length != 2 || !string.Equals(segments[0], "board", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            albumId = segments[1];
            albumUrl = resolved.AbsoluteUri;
            return !string.IsNullOrWhiteSpace(albumId);
        }

        private static int? ParseAlbumCount(string label)
        {
            int start = (label ?? string.Empty).IndexOf("专辑", StringComparison.Ordinal);
            if (start < 0) return null;
            for (int index = start + 2; index < label.Length; index++)
            {
                if (!char.IsDigit(label[index])) continue;
                int end = index + 1;
                while (end < label.Length && char.IsDigit(label[end])) end++;
                return int.TryParse(label.Substring(index, end - index), out int count) ? count : (int?)null;
            }
            return null;
        }

        private static int? ParseTrailingCount(string text)
        {
            string value = (text ?? string.Empty).Trim();
            int start = value.Length;
            while (start > 0 && char.IsDigit(value[start - 1])) start--;
            return start < value.Length && int.TryParse(value.Substring(start), out int count) ? count : (int?)null;
        }

        public void CancelFavoritesScan(string requestId)
        {
            TaskCompletionSource<FavoriteEvidence> waiter;
            lock (_favoriteScanLock)
            {
                if (!string.IsNullOrEmpty(requestId)
                    && !string.Equals(_favoriteScanRequestId, requestId, StringComparison.Ordinal)) return;
                if (string.IsNullOrEmpty(_favoriteScanRequestId)) return;
                _favoriteScanCancelled = true;
                Trace.LogAlways("xhs-scan op=" + _favoriteScanRequestId + " event=cancel");
                waiter = _favoriteScanWaiter;
            }
            waiter?.TrySetResult(new FavoriteEvidence { HasMore = false });
        }

        private bool FavoriteScanCancelled(string requestId)
        {
            lock (_favoriteScanLock)
            {
                return _favoriteScanCancelled
                    || !string.Equals(_favoriteScanRequestId, requestId, StringComparison.Ordinal);
            }
        }

        public async Task<XhsSessionResult> ClearCookiesAndVerifyAsync()
        {
            await InitializeAsync();
            await _checkGate.WaitAsync();
            try
            {
                IReadOnlyList<CoreWebView2Cookie> cookies =
                    await _core.CookieManager.GetCookiesAsync(null);
                foreach (CoreWebView2Cookie cookie in cookies)
                {
                    if (IsXiaohongshuDomain(cookie.Domain))
                    {
                        _core.CookieManager.DeleteCookie(cookie);
                    }
                }

                IReadOnlyList<CoreWebView2Cookie> remaining =
                    await _core.CookieManager.GetCookiesAsync(null);
                if (remaining.Any(cookie => IsXiaohongshuDomain(cookie.Domain)))
                {
                    return Result("REAUTH_REQUIRED", "小红书域 Cookie 未能完整清除，连接记录已保留");
                }
            }
            catch
            {
                return Result("REAUTH_REQUIRED", "清除小红书域 Cookie 失败，连接记录已保留");
            }
            finally
            {
                _checkGate.Release();
            }

            XhsSessionResult verification = await CheckSessionAsync();
            if (verification.Status == "NOT_CONNECTED" && verification.SessionInvalidated)
            {
                return Result("NOT_CONNECTED", "小红书域 Cookie 已清除并复验会话无效", sessionInvalidated: true);
            }

            return Result(
                verification.Status == "CONNECTED" ? "CONNECTED" : "REAUTH_REQUIRED",
                verification.Status == "CONNECTED"
                    ? "清除 Cookie 后页面仍确认登录，连接记录已保留"
                    : "清除 Cookie 后无法确认会话已失效，连接记录已保留");
        }

        public void CloseForShutdown()
        {
            _shuttingDown = true;
            Close();
        }

        private void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (_shuttingDown)
            {
                return;
            }

            args.Cancel = true;
            Hide();
            UserRequestedClose?.Invoke(this, EventArgs.Empty);
        }

        private XhsSessionResult Result(
            string status,
            string message,
            bool sessionInvalidated = false)
        {
            UpdateWindowStatus(status, message);
            return new XhsSessionResult(status, message, _browserProfile, sessionInvalidated);
        }

        private async void CopyCurrentLink(object sender, EventArgs args)
        {
            string currentUrl = _core?.Source;
            if (string.IsNullOrWhiteSpace(currentUrl))
            {
                _windowStatus.Text = "当前页面还没有可复制的链接";
                return;
            }

            try
            {
                Clipboard.SetText(currentUrl);
                _copyLink.Text = "已复制";
                _windowStatus.Text = "当前小红书页面链接已复制，可粘贴到内容接入";
                await Task.Delay(1200);
                if (!_copyLink.IsDisposed)
                {
                    _copyLink.Text = "复制当前链接";
                }
            }
            catch
            {
                _windowStatus.Text = "复制失败，请稍后重试";
            }
        }

        private async void RecheckSession(object sender, EventArgs args)
        {
            _recheck.Enabled = false;
            _windowStatus.Text = "正在检查小红书登录状态…";
            try
            {
                await CheckSessionAsync();
            }
            finally
            {
                if (!_recheck.IsDisposed)
                {
                    _recheck.Enabled = true;
                }
            }
        }

        private void UpdateWindowStatus(string status, string message)
        {
            if (_windowStatus.IsDisposed)
            {
                return;
            }

            if (status == "CONNECTED")
            {
                _windowStatus.Text = "登录状态已确认。你可以继续浏览并复制当前链接";
            }
            else if (status == "RISK_CONTROLLED")
            {
                _windowStatus.Text = "当前页面需要人工验证。请在下方网页按提示完成后点击“重新检查”";
            }
            else
            {
                _windowStatus.Text = message;
            }
        }

        private async Task<XhsSessionResult> RiskOrUnavailableAsync(string unavailableMessage)
        {
            if (await HasVisibleRiskChallengeAsync())
            {
                return Result(
                    "RISK_CONTROLLED",
                    "当前小红书页面需要人工验证，请在登录窗口网页中按提示完成后点击“重新检查”");
            }

            if (!_riskControlled)
            {
                return Result("REAUTH_REQUIRED", unavailableMessage);
            }

            return Result(
                "REAUTH_REQUIRED",
                "平台限制了本次检查，但当前页面没有可操作的验证入口，请稍后重新检查");
        }

        private async Task<bool> NavigateAndWaitAsync(string url)
        {
            var waiter = NewWaiter<bool>();
            EventHandler<CoreWebView2NavigationCompletedEventArgs> handler = null;
            handler = (sender, args) =>
            {
                _core.NavigationCompleted -= handler;
                waiter.TrySetResult(args.IsSuccess);
            };
            _core.NavigationCompleted += handler;
            _core.Navigate(url);

            Task completed = await Task.WhenAny(waiter.Task, Task.Delay(CheckTimeoutMilliseconds));
            _core.NavigationCompleted -= handler;
            return completed == waiter.Task && await waiter.Task;
        }

        private static async Task<T> WaitForResponseAsync<T>(Task<T> response, int timeoutMilliseconds = CheckTimeoutMilliseconds)
        {
            Task completed = await Task.WhenAny(response, Task.Delay(timeoutMilliseconds));
            if (completed != response)
            {
                Trace.LogAlways("xhs-wait-timeout " + typeof(T).Name + " ms=" + timeoutMilliseconds);
                return default;
            }
            return await response;
        }

        private void OnFavoritePageRequested(object sender, CoreWebView2WebResourceRequestedEventArgs args)
        {
            if (!Uri.TryCreate(args.Request.Uri, UriKind.Absolute, out Uri uri)
                || !IsXiaohongshuDomain(uri.Host)) return;
            bool album = string.Equals(uri.AbsolutePath, BoardNotePath, StringComparison.OrdinalIgnoreCase);
            if (!album && !string.Equals(uri.AbsolutePath, FavoritePagePath, StringComparison.OrdinalIgnoreCase)) return;

            string referer = args.Request.Headers.Contains("Referer") ? args.Request.Headers.GetHeader("Referer") : null;
            lock (_favoriteScanLock)
            {
                string scanId = null;
                if (_favoriteScanActive && !_favoriteScanCancelled && _favoriteScanIsAlbum == album
                    && Uri.TryCreate(_favoriteScanCollectionUrl, UriKind.Absolute, out Uri expected))
                {
                    // Cross-origin API requests may carry only the origin in Referer.
                    Uri.TryCreate(referer, UriKind.Absolute, out Uri page);
                    bool fullReferer = page != null && page.AbsolutePath != "/";
                    if (!fullReferer) Uri.TryCreate(_core.Source, UriKind.Absolute, out page);
                    string scopeKey = album ? "board_id" : "user_id";
                    string scopeId = expected.AbsolutePath.TrimEnd('/').Split('/').Last();
                    string[] query = uri.Query.TrimStart('?').Split('&');
                    string explicitScope = query.FirstOrDefault(part => part.StartsWith(scopeKey + "=", StringComparison.Ordinal));
                    bool scopeMatches = explicitScope == scopeKey + "=" + scopeId;
                    bool pageMatches = page != null && IsXiaohongshuDomain(page.Host)
                        && string.Equals(page.AbsolutePath, expected.AbsolutePath, StringComparison.Ordinal)
                        && (album || (page.Query.TrimStart('?').Split('&').Contains("tab=fav")
                            && page.Query.TrimStart('?').Split('&').Contains("subTab=note")));
                    if ((explicitScope == null && pageMatches)
                        || (scopeMatches && (pageMatches || !fullReferer)))
                        scanId = _favoriteScanRequestId;
                }
                if (!_favoritePageRequests.TryGetValue(uri.AbsoluteUri, out var requests))
                {
                    requests = new Queue<(string, int, long)>();
                    _favoritePageRequests.Add(uri.AbsoluteUri, requests);
                }
                int number = ++_favoritePageRequestNumber;
                requests.Enqueue((scanId, number, Environment.TickCount64));
                Trace.LogAlways("xhs-page op=" + (scanId ?? "-") + " event=request page=" + number
                    + " scope=" + (album ? "album" : "notes") + " album=" + Trace.XhsId(scanId == null ? null : _favoriteScanAlbumId));
            }
        }

        private async void OnResponseReceived(
            object sender,
            CoreWebView2WebResourceResponseReceivedEventArgs args)
        {
            (string ScanId, int Number, long Started) pageRequest = default;
            int status = 0;
            string outcome = "unreadable";
            try
            {
                Uri uri;
                if (!Uri.TryCreate(args.Request.Uri, UriKind.Absolute, out uri)
                    || !IsXiaohongshuDomain(uri.Host))
                {
                    return;
                }

                status = args.Response.StatusCode;
                bool isUserMe = string.Equals(uri.AbsolutePath, UserMePath, StringComparison.OrdinalIgnoreCase);
                bool isFavoritePage = string.Equals(uri.AbsolutePath, FavoritePagePath, StringComparison.OrdinalIgnoreCase);
                bool isBoardNotePage = string.Equals(uri.AbsolutePath, BoardNotePath, StringComparison.OrdinalIgnoreCase);
                if (!isUserMe && !isFavoritePage && !isBoardNotePage) return;
                var ambiguous = false;
                if (!isUserMe)
                {
                    lock (_favoriteScanLock)
                    {
                        if (_favoritePageRequests.TryGetValue(uri.AbsoluteUri, out var requests))
                        {
                            pageRequest = requests.Dequeue();
                            // With overlaps from different contexts, response order cannot establish identity.
                            ambiguous = requests.Any(request => request.ScanId != pageRequest.ScanId);
                            if (ambiguous)
                            {
                                var ignored = requests.Select(request => ((string)null, request.Number, request.Started)).ToArray();
                                requests.Clear();
                                foreach (var request in ignored) requests.Enqueue(request);
                            }
                            if (requests.Count == 0) _favoritePageRequests.Remove(uri.AbsoluteUri);
                        }
                    }
                    if (ambiguous || pageRequest.ScanId == null) outcome = "unmatched";
                }
                if (!isUserMe && (ambiguous || pageRequest.ScanId == null)
                    && !(isFavoritePage && _favoriteWaiter != null))
                {
                    return;
                }

                if ((status == 412 || status == 429) && (isUserMe || _favoriteWaiter != null
                    || (!ambiguous && IsCurrentFavoritePage(pageRequest.ScanId))))
                {
                    _riskControlled = true;
                }

                using (Stream content = await args.Response.GetContentAsync())
                {
                    if (content == null)
                    {
                        return;
                    }

                    using (var reader = new StreamReader(content, Encoding.UTF8))
                    {
                        string body = await reader.ReadToEndAsync();
                        using (JsonDocument document = JsonDocument.Parse(body))
                        {
                            if (isUserMe)
                            {
                                _userMeWaiter?.TrySetResult(ParseUserMe(status, document.RootElement));
                            }
                            else
                            {
                                FavoriteEvidence evidence = isBoardNotePage
                                    ? ParseBoardFavoritePage(status, document.RootElement)
                                    : ParseFavoritePage(status, document.RootElement);
                                if (isFavoritePage) _favoriteWaiter?.TrySetResult(evidence);
                                TaskCompletionSource<FavoriteEvidence> scanWaiter = null;
                                lock (_favoriteScanLock)
                                {
                                    if (!ambiguous && IsCurrentFavoritePage(pageRequest.ScanId))
                                    {
                                        int before = _favoriteScanCandidates.Count;
                                        MergeFavoriteCandidatesLocked(evidence.Candidates);
                                        // 后到的 has_more=true 推翻先前的末页判定，避免预取空响应把扫描提前截断。
                                        if (evidence.IsAuthenticatedBusinessResponse && evidence.HasMore)
                                        {
                                            _favoriteLastPage = null;
                                        }
                                        else if (evidence.IsAuthenticatedBusinessResponse && !evidence.HasMore)
                                        {
                                            _favoriteLastPage = evidence;
                                        }
                                        scanWaiter = _favoriteScanWaiter;
                                        outcome = "accepted valid=" + evidence.IsAuthenticatedBusinessResponse
                                            + " has_more=" + evidence.HasMore + " items=" + evidence.Candidates.Count
                                            + " added=" + (_favoriteScanCandidates.Count - before);
                                    }
                                    else if (pageRequest.ScanId != null && !ambiguous) outcome = "inactive";
                                }
                                scanWaiter?.TrySetResult(evidence);
                            }
                        }
                    }
                }
            }
            catch
            {
                // 响应体只在内存解析成布尔状态与用户 ID；不写文件、不记录正文。
            }
            finally
            {
                if (pageRequest.Number != 0)
                    Trace.LogAlways("xhs-page op=" + (pageRequest.ScanId ?? "-") + " event=response page=" + pageRequest.Number
                        + " status=" + status + " result=" + outcome + " ms=" + (Environment.TickCount64 - pageRequest.Started));
            }
        }

        private bool IsCurrentFavoritePage(string requestId)
        {
            return requestId != null && _favoriteScanActive && !_favoriteScanCancelled
                && string.Equals(_favoriteScanRequestId, requestId, StringComparison.Ordinal);
        }

        private static UserMeEvidence ParseUserMe(int status, JsonElement root)
        {
            JsonElement data;
            JsonElement userIdElement = default(JsonElement);
            string userId = string.Empty;
            bool hasData = root.TryGetProperty("data", out data);
            bool hasUserId = hasData
                && data.ValueKind == JsonValueKind.Object
                && data.TryGetProperty("user_id", out userIdElement)
                && userIdElement.ValueKind == JsonValueKind.String;
            if (hasUserId)
            {
                userId = userIdElement.GetString() ?? string.Empty;
            }

            return new UserMeEvidence
            {
                HasUserId = status == 200 && hasUserId && !string.IsNullOrWhiteSpace(userId),
                IsAnonymous = status == 401 || status == 403,
                UserId = userId,
            };
        }

        private static FavoriteEvidence ParseFavoritePage(int status, JsonElement root)
        {
            JsonElement data;
            JsonElement notes = default(JsonElement);
            JsonElement hasMore = default(JsonElement);
            bool hasData = root.TryGetProperty("data", out data) && data.ValueKind == JsonValueKind.Object;
            bool hasNotes = hasData && data.TryGetProperty("notes", out notes) && notes.ValueKind == JsonValueKind.Array;
            bool hasMoreValue = hasData && data.TryGetProperty("has_more", out hasMore)
                && (hasMore.ValueKind == JsonValueKind.True || hasMore.ValueKind == JsonValueKind.False);
            var candidates = new List<XhsFavoriteCandidate>();
            if (hasNotes)
            {
                foreach (JsonElement note in notes.EnumerateArray())
                {
                    string id = FirstString(note, "note_id", "id", "noteId");
                    if (string.IsNullOrWhiteSpace(id)) continue;
                    JsonElement card;
                    JsonElement source = note.TryGetProperty("note_card", out card) && card.ValueKind == JsonValueKind.Object
                        ? card : note;
                    string token = FirstString(note, "xsec_token", "xsecToken");
                    string sourceToken = FirstString(note, "xsec_source", "xsecSource");
                    if (string.IsNullOrWhiteSpace(sourceToken))
                    {
                        sourceToken = FirstString(source, "xsec_source", "xsecSource");
                    }
                    string url = "https://www.xiaohongshu.com/explore/" + Uri.EscapeDataString(id);
                    if (!string.IsNullOrWhiteSpace(token) && !string.IsNullOrWhiteSpace(sourceToken))
                    {
                        url += "?xsec_token=" + Uri.EscapeDataString(token)
                            + "&xsec_source=" + Uri.EscapeDataString(sourceToken);
                    }
                    JsonElement user;
                    string author = source.TryGetProperty("user", out user) && user.ValueKind == JsonValueKind.Object
                        ? FirstString(user, "nickname", "name") : string.Empty;
                    candidates.Add(new XhsFavoriteCandidate
                    {
                        CandidateId = "note:" + id,
                        Id = id,
                        Title = FirstString(source, "display_title", "title"),
                        Author = author,
                        Type = FirstString(source, "type", "note_type"),
                        Url = url,
                        ThumbnailUrl = ParseCoverUrl(source),
                    });
                }
            }
            return new FavoriteEvidence
            {
                IsAuthenticatedBusinessResponse = status == 200 && hasNotes && hasMoreValue
                    && candidates.Count == notes.GetArrayLength(),
                IsAnonymous = status == 401 || status == 403,
                IsRiskControlled = status == 412 || status == 429,
                HasMore = hasMoreValue && hasMore.ValueKind == JsonValueKind.True,
                IsEmptyPage = status == 200 && hasNotes && notes.GetArrayLength() == 0,
                Candidates = candidates,
            };
        }

        private static FavoriteEvidence ParseBoardFavoritePage(int status, JsonElement root)
        {
            JsonElement code;
            JsonElement success;
            bool validEnvelope = root.ValueKind == JsonValueKind.Object
                && root.TryGetProperty("code", out code)
                && code.ValueKind == JsonValueKind.Number
                && code.TryGetInt32(out int codeValue)
                && codeValue == 0
                && root.TryGetProperty("success", out success)
                && success.ValueKind == JsonValueKind.True;
            FavoriteEvidence evidence = ParseFavoritePage(status, root);
            evidence.IsAuthenticatedBusinessResponse &= validEnvelope;
            return evidence;
        }

        private static string ParseCoverUrl(JsonElement source)
        {
            if (source.ValueKind != JsonValueKind.Object) return string.Empty;
            JsonElement cover;
            if (source.TryGetProperty("cover", out cover) && cover.ValueKind == JsonValueKind.Object)
            {
                string url = FirstString(cover, "url_default", "url_pre", "url");
                if (!string.IsNullOrWhiteSpace(url)) return NormalizeCoverUrl(url);
            }
            JsonElement images;
            if (source.TryGetProperty("image_list", out images) && images.ValueKind == JsonValueKind.Array)
            {
                foreach (JsonElement image in images.EnumerateArray())
                {
                    string url = FirstString(image, "url_default", "url_pre", "url");
                    if (!string.IsNullOrWhiteSpace(url)) return NormalizeCoverUrl(url);
                }
            }
            return string.Empty;
        }

        private static string NormalizeCoverUrl(string url)
        {
            string value = (url ?? string.Empty).Trim();
            if (value.StartsWith("//", StringComparison.Ordinal))
            {
                value = "https:" + value;
            }
            if (!value.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                && !value.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                return string.Empty;
            }
            return value;
        }

        private static string FirstString(JsonElement element, params string[] names)
        {
            if (element.ValueKind != JsonValueKind.Object) return string.Empty;
            foreach (string name in names)
            {
                JsonElement value;
                if (!element.TryGetProperty(name, out value)) continue;
                if (value.ValueKind == JsonValueKind.String) return value.GetString() ?? string.Empty;
                if (value.ValueKind == JsonValueKind.Number) return value.ToString();
            }
            return string.Empty;
        }

        private async Task<bool> IsLoginWallAsync()
        {
            try
            {
                const string script = @"(function(){
  var path = location.pathname || '';
  var loginPath = /^\/login(?:\/|$)/i.test(path);
  var selectors = '[role=dialog],[aria-modal=true],[class*=login],[class*=Login],[class*=modal]';
  var wallText = /请先登录|登录后查看|扫码登录|手机号登录|验证码登录/;
  var visibleWall = Array.prototype.some.call(document.querySelectorAll(selectors), function (el) {
    var rect = el.getBoundingClientRect();
    var visible = rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    return visible && wallText.test((el.innerText || el.textContent || '').replace(/\s/g, ''));
  });
  return JSON.stringify({ loginWall: loginPath || visibleWall });
})();";
                string encoded = await _core.ExecuteScriptAsync(script);
                string json = JsonSerializer.Deserialize<string>(encoded);
                using (JsonDocument document = JsonDocument.Parse(json))
                {
                    return document.RootElement.GetProperty("loginWall").GetBoolean();
                }
            }
            catch
            {
                return true;
            }
        }

        private async Task<bool> HasVisibleRiskChallengeAsync()
        {
            try
            {
                const string script = @"(function(){
  var textPattern = /验证码|滑块|安全验证|访问异常|操作频繁|请完成验证/;
  var challengeSelector = '[class*=captcha],[class*=Captcha],[class*=verify],[class*=Verify],[class*=security],[class*=challenge],[id*=captcha],[id*=verify],[id*=challenge]';
  var selectors = '[role=dialog],[aria-modal=true],' + challengeSelector;
  function isVisible(el) {
    var rect = el.getBoundingClientRect();
    var style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  }
  var visibleChallenge = Array.prototype.some.call(document.querySelectorAll(selectors), function (el) {
    if (!isVisible(el)) return false;
    var textMatches = textPattern.test((el.innerText || el.textContent || '').replace(/\s/g, ''));
    var isNamedChallenge = el.matches(challengeSelector);
    var hasChallengeControl = !!el.querySelector('iframe[src*=captcha],iframe[src*=verify],canvas,input[type=range]');
    return textMatches && (isNamedChallenge || hasChallengeControl || el.matches('[role=dialog],[aria-modal=true]'));
  });
  var pageSignal = /captcha|verify|verification|security-check|challenge/i.test(location.href) ||
    textPattern.test((document.title || '').replace(/\s/g, ''));
  var renderedPageText = document.body ? (document.body.innerText || '').replace(/\s/g, '') : '';
  var fullPageChallenge = pageSignal && textPattern.test(renderedPageText);
  return JSON.stringify({ visibleChallenge: visibleChallenge || fullPageChallenge });
})();";
                string encoded = await _core.ExecuteScriptAsync(script);
                string json = JsonSerializer.Deserialize<string>(encoded);
                using (JsonDocument document = JsonDocument.Parse(json))
                {
                    return document.RootElement.GetProperty("visibleChallenge").GetBoolean();
                }
            }
            catch
            {
                return false;
            }
        }

        private bool IsExpectedFavoritePage(string userId)
        {
            Uri current;
            string expectedPath = "/user/profile/" + userId;
            if (!Uri.TryCreate(_core.Source, UriKind.Absolute, out current)
                || !IsXiaohongshuDomain(current.Host)
                || !string.Equals(
                    Uri.UnescapeDataString(current.AbsolutePath).TrimEnd('/'),
                    expectedPath.TrimEnd('/'),
                    StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            bool hasFavoriteTab = false;
            bool hasNoteSubTab = false;
            foreach (string part in current.Query.TrimStart('?').Split('&'))
            {
                string[] pair = part.Split(new[] { '=' }, 2);
                if (pair.Length != 2)
                {
                    continue;
                }

                string key = Uri.UnescapeDataString(pair[0]);
                string value = Uri.UnescapeDataString(pair[1]);
                hasFavoriteTab |= string.Equals(key, "tab", StringComparison.OrdinalIgnoreCase)
                    && string.Equals(value, "fav", StringComparison.OrdinalIgnoreCase);
                hasNoteSubTab |= string.Equals(key, "subTab", StringComparison.OrdinalIgnoreCase)
                    && string.Equals(value, "note", StringComparison.OrdinalIgnoreCase);
            }

            return hasFavoriteTab && hasNoteSubTab;
        }

        private static bool IsXiaohongshuDomain(string domain)
        {
            string host = (domain ?? string.Empty).TrimStart('.');
            return string.Equals(host, "xiaohongshu.com", StringComparison.OrdinalIgnoreCase)
                || host.EndsWith(".xiaohongshu.com", StringComparison.OrdinalIgnoreCase);
        }

        private static TaskCompletionSource<T> NewWaiter<T>()
        {
            return new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        private sealed class UserMeEvidence
        {
            public bool HasUserId;
            public bool IsAnonymous;
            public string UserId;
        }

        private sealed class FavoriteEvidence
        {
            public bool IsAuthenticatedBusinessResponse;
            public bool IsAnonymous;
            public bool IsRiskControlled;
            public bool HasMore;
            public bool IsEmptyPage;
            public List<XhsFavoriteCandidate> Candidates = new List<XhsFavoriteCandidate>();
        }

        private sealed class AlbumDirectoryEvidence
        {
            public bool IsConfirmed;
            public List<XhsFavoriteAlbum> Albums = new List<XhsFavoriteAlbum>();
            public Dictionary<string, string> Urls = new Dictionary<string, string>(StringComparer.Ordinal);
        }
    }
}
