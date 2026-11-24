using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace LoginShell
{
    internal sealed class ZhihuCandidate
    {
        public string CandidateId { get; set; }
        public string Title { get; set; }
        public string Author { get; set; }
        public string Url { get; set; }
        public string SourceType { get; set; }
    }

    internal sealed class ZhihuContent
    {
        public string Title { get; set; }
        public string Author { get; set; }
        public string Text { get; set; }
    }

    internal sealed class ZhihuOperationResult
    {
        public string Status { get; set; }
        public string Message { get; set; }
        public string BrowserProfile { get; set; }
        public bool SessionInvalidated { get; set; }
        public List<ZhihuCandidate> Candidates { get; set; }
        public ZhihuContent Content { get; set; }
    }

    internal sealed class ZhihuLoginForm : Form
    {
        private const string SignInUrl = "https://www.zhihu.com/signin";
        private const string MeUrl = "https://www.zhihu.com/api/v4/me";
        private readonly CoreWebView2Environment _environment;
        private readonly string _browserProfile;
        private readonly WebView2 _view = new WebView2();
        private readonly Label _status = new Label();
        private readonly Button _recheck = new Button();
        private CoreWebView2 _core;
        private TaskCompletionSource<HttpEvidence> _meWaiter;
        private TaskCompletionSource<HttpEvidence> _collectionWaiter;
        private TaskCompletionSource<HttpEvidence> _itemsWaiter;
        private TaskCompletionSource<HttpEvidence> _contentWaiter;
        private string _activeCollectionId;
        private string _activeContentId;
        private string _activeContentType;
        private bool _initialized;
        private bool _shuttingDown;

        public event EventHandler UserRequestedClose;

        public ZhihuLoginForm(CoreWebView2Environment environment, string browserProfile)
        {
            _environment = environment;
            _browserProfile = browserProfile;
            Text = "知乎登录";
            Width = 1080;
            Height = 780;
            StartPosition = FormStartPosition.CenterParent;

            var actions = new TableLayoutPanel
            {
                Dock = DockStyle.Top,
                Height = 42,
                ColumnCount = 2,
                Padding = new Padding(10, 6, 10, 6),
            };
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            _status.Dock = DockStyle.Fill;
            _status.TextAlign = ContentAlignment.MiddleLeft;
            _status.Text = "请在下方知乎页面完成登录";
            _recheck.AutoSize = true;
            _recheck.Text = "重新检查";
            _recheck.Click += async (sender, args) =>
            {
                ZhihuOperationResult result = await CheckSessionAsync();
                _status.Text = result.Message;
            };
            actions.Controls.Add(_status, 0, 0);
            actions.Controls.Add(_recheck, 1, 0);
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
            _core.WebResourceResponseReceived += OnResponseReceived;
            _initialized = true;
        }

        public async Task OpenLoginPageAsync()
        {
            await InitializeAsync();
            await NavigateAndWaitAsync(SignInUrl);
        }

        public async Task<ZhihuOperationResult> CheckSessionAsync()
        {
            await InitializeAsync();
            _meWaiter = NewWaiter();
            await NavigateAndWaitAsync(MeUrl);
            HttpEvidence evidence = await WaitEvidenceAsync(_meWaiter.Task, 9000);
            _meWaiter = null;
            if (evidence == null)
            {
                return Result("REAUTH_REQUIRED", "知乎账号业务响应暂时无法确认登录状态");
            }

            string accountId = evidence.StatusCode == 200 ? ReadAccountId(evidence.Body) : null;
            _lastAccountId = accountId;
            if (!string.IsNullOrWhiteSpace(accountId))
            {
                return Result("CONNECTED", "知乎账号业务响应已确认登录");
            }
            if (evidence.StatusCode == 401 || evidence.StatusCode == 403)
            {
                return Result("NOT_CONNECTED", "知乎页面未返回已登录账号", true);
            }
            return Result("REAUTH_REQUIRED", "知乎账号业务响应格式无法确认");
        }

        public async Task<ZhihuOperationResult> ScanFavoritesAsync(string folderUrl)
        {
            ZhihuOperationResult session = await CheckSessionAsync();
            if (session.Status != "CONNECTED")
            {
                return session;
            }

            Uri folder;
            if (!Uri.TryCreate(folderUrl, UriKind.Absolute, out folder)
                || !IsZhihuHost(folder.Host)
                || !Regex.IsMatch(folder.AbsolutePath, @"^/collections?/(?<id>\d+)/?$") )
            {
                return Result("REAUTH_REQUIRED", "请输入一个知乎收藏夹链接");
            }

            Match folderMatch = Regex.Match(folder.AbsolutePath, @"^/collections?/(?<id>\d+)/?$");
            _activeCollectionId = folderMatch.Groups["id"].Value;
            _collectionWaiter = NewWaiter();
            _itemsWaiter = NewWaiter();
            await NavigateAndWaitAsync(folder.AbsoluteUri);
            HttpEvidence collection = await WaitEvidenceAsync(_collectionWaiter.Task, 12000);
            HttpEvidence items = await WaitEvidenceAsync(_itemsWaiter.Task, 12000);
            _collectionWaiter = null;
            _itemsWaiter = null;
            if (collection == null || collection.StatusCode != 200
                || !CollectionBelongsTo(collection.Body, ReadAccountIdFromLastCheck()))
            {
                return Result("REAUTH_REQUIRED", "未能通过知乎收藏夹业务响应确认该收藏夹属于当前账号");
            }
            if (items == null || items.StatusCode != 200)
            {
                return Result("REAUTH_REQUIRED", "知乎收藏夹没有返回可读取的内容列表");
            }

            List<ZhihuCandidate> candidates = ParseCandidates(items.Body).ToList();
            return new ZhihuOperationResult
            {
                Status = "CONNECTED",
                Message = "知乎收藏夹前 10 条候选已读取",
                BrowserProfile = _browserProfile,
                Candidates = candidates,
            };
        }

        private string _lastAccountId;

        private string ReadAccountIdFromLastCheck()
        {
            return _lastAccountId;
        }

        public async Task<ZhihuOperationResult> ReadContentAsync(string url)
        {
            ZhihuOperationResult session = await CheckSessionAsync();
            if (session.Status != "CONNECTED")
            {
                return session;
            }

            Uri source;
            if (!Uri.TryCreate(url, UriKind.Absolute, out source) || !IsZhihuHost(source.Host))
            {
                return Result("REAUTH_REQUIRED", "知乎原文链接无效");
            }
            Match answer = Regex.Match(source.AbsolutePath, @"^/question/(?<question>\d+)/answer/(?<id>\d+)");
            Match article = Regex.Match(source.AbsolutePath, @"^/p/(?<id>\d+)");
            if (answer.Success)
            {
                _activeContentType = "answer";
                _activeContentId = answer.Groups["id"].Value;
            }
            else if (article.Success && source.Host.Equals("zhuanlan.zhihu.com", StringComparison.OrdinalIgnoreCase))
            {
                _activeContentType = "article";
                _activeContentId = article.Groups["id"].Value;
            }
            else
            {
                return Result("REAUTH_REQUIRED", "仅支持知乎回答或文章原文链接");
            }

            _contentWaiter = NewWaiter();
            await NavigateAndWaitAsync(source.AbsoluteUri);
            HttpEvidence evidence = await WaitEvidenceAsync(_contentWaiter.Task, 15000);
            _contentWaiter = null;
            if (evidence == null || evidence.StatusCode != 200)
            {
                return Result("REAUTH_REQUIRED", "知乎原文页没有返回可读取的完整正文");
            }

            string html = ReadString(ReadDataObject(ParseJson(evidence.Body)), "content");
            if (string.IsNullOrWhiteSpace(html))
            {
                return Result("REAUTH_REQUIRED", "知乎原文业务响应不含完整正文");
            }
            string text = await HtmlToTextAsync(html);
            if (string.IsNullOrWhiteSpace(text))
            {
                return Result("REAUTH_REQUIRED", "知乎原文正文为空");
            }

            JsonElement data = ReadDataObject(ParseJson(evidence.Body));
            string title = ReadString(data, "title");
            if (string.IsNullOrWhiteSpace(title))
            {
                title = ReadString(ReadObject(data, "question"), "title");
            }
            return new ZhihuOperationResult
            {
                Status = "CONNECTED",
                Message = "知乎原文正文已读取",
                BrowserProfile = _browserProfile,
                Content = new ZhihuContent
                {
                    Title = title ?? "知乎内容",
                    Author = ReadString(ReadObject(data, "author"), "name"),
                    Text = text,
                },
            };
        }

        public async Task<ZhihuOperationResult> ClearCookiesAndVerifyAsync()
        {
            await InitializeAsync();
            try
            {
                IReadOnlyList<CoreWebView2Cookie> cookies = await _core.CookieManager.GetCookiesAsync(null);
                foreach (CoreWebView2Cookie cookie in cookies)
                {
                    if (cookie.Domain.IndexOf("zhihu.com", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        _core.CookieManager.DeleteCookie(cookie);
                    }
                }
                if ((await _core.CookieManager.GetCookiesAsync(null)).Any(cookie =>
                    cookie.Domain.IndexOf("zhihu.com", StringComparison.OrdinalIgnoreCase) >= 0))
                {
                    return Result("REAUTH_REQUIRED", "知乎会话未能清除，连接记录已保留");
                }
            }
            catch
            {
                return Result("REAUTH_REQUIRED", "清除知乎会话失败，连接记录已保留");
            }

            ZhihuOperationResult verification = await CheckSessionAsync();
            if (verification.Status == "NOT_CONNECTED" && verification.SessionInvalidated)
            {
                return Result("NOT_CONNECTED", "知乎会话已清除并复验无效", true);
            }
            return Result("REAUTH_REQUIRED", "清除知乎会话后仍无法确认登录已失效");
        }

        public void CloseForShutdown()
        {
            _shuttingDown = true;
            Close();
        }

        private async void OnResponseReceived(object sender, CoreWebView2WebResourceResponseReceivedEventArgs args)
        {
            try
            {
                Uri uri = new Uri(args.Request.Uri);
                if (!IsZhihuHost(uri.Host)) return;
                string path = uri.AbsolutePath;
                bool isMe = path.Equals("/api/v4/me", StringComparison.OrdinalIgnoreCase);
                bool isCollection = !string.IsNullOrEmpty(_activeCollectionId)
                    && path.Equals("/api/v4/collections/" + _activeCollectionId, StringComparison.OrdinalIgnoreCase);
                bool isItems = !string.IsNullOrEmpty(_activeCollectionId)
                    && path.StartsWith("/api/v4/collections/" + _activeCollectionId + "/items", StringComparison.OrdinalIgnoreCase);
                bool isAnswer = _activeContentType == "answer"
                    && path.Equals("/api/v4/answers/" + _activeContentId, StringComparison.OrdinalIgnoreCase);
                bool isArticle = _activeContentType == "article"
                    && (path.Equals("/api/articles/" + _activeContentId, StringComparison.OrdinalIgnoreCase)
                        || path.Equals("/api/v4/articles/" + _activeContentId, StringComparison.OrdinalIgnoreCase));
                if (!(isMe || isCollection || isItems || isAnswer || isArticle)) return;
                string body = await ReadResponseBodyAsync(args.Response);
                var evidence = new HttpEvidence(args.Response.StatusCode, body);
                if (isMe) _meWaiter?.TrySetResult(evidence);
                else if (isCollection) _collectionWaiter?.TrySetResult(evidence);
                else if (isItems) _itemsWaiter?.TrySetResult(evidence);
                else _contentWaiter?.TrySetResult(evidence);
            }
            catch
            {
                // Upstream responses that cannot be read are treated as unavailable.
            }
        }

        private static async Task<string> ReadResponseBodyAsync(CoreWebView2WebResourceResponseView response)
        {
            using (Stream stream = await response.GetContentAsync())
            using (var reader = new StreamReader(stream))
            {
                return await reader.ReadToEndAsync();
            }
        }

        private async Task<string> HtmlToTextAsync(string html)
        {
            string literal = JsonSerializer.Serialize(html);
            string raw = await _core.ExecuteScriptAsync(
                "(()=>{const e=document.createElement('div');e.innerHTML=" + literal
                    + ";return e.innerText||e.textContent||''})()");
            return JsonSerializer.Deserialize<string>(raw) ?? string.Empty;
        }

        private async Task<bool> NavigateAndWaitAsync(string url)
        {
            var waiter = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void OnCompleted(object sender, CoreWebView2NavigationCompletedEventArgs args)
            {
                _core.NavigationCompleted -= OnCompleted;
                waiter.TrySetResult(args.IsSuccess);
            }
            _core.NavigationCompleted += OnCompleted;
            _core.Navigate(url);
            Task completed = await Task.WhenAny(waiter.Task, Task.Delay(20000));
            return completed == waiter.Task && await waiter.Task;
        }

        private static async Task<HttpEvidence> WaitEvidenceAsync(Task<HttpEvidence> task, int milliseconds)
        {
            Task completed = await Task.WhenAny(task, Task.Delay(milliseconds));
            return completed == task ? await task : null;
        }

        private async void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (_shuttingDown) return;
            args.Cancel = true;
            Hide();
            UserRequestedClose?.Invoke(this, EventArgs.Empty);
            await Task.CompletedTask;
        }

        private ZhihuOperationResult Result(string status, string message, bool invalidated = false)
        {
            _status.Text = message;
            return new ZhihuOperationResult
            {
                Status = status,
                Message = message,
                BrowserProfile = _browserProfile,
                SessionInvalidated = invalidated,
            };
        }

        private static TaskCompletionSource<HttpEvidence> NewWaiter()
        {
            return new TaskCompletionSource<HttpEvidence>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        private static string ReadAccountId(string json)
        {
            try
            {
                JsonElement data = ReadDataObject(ParseJson(json));
                string id = ReadString(data, "id");
                if (string.IsNullOrWhiteSpace(id)) id = ReadString(data, "url_token");
                return id;
            }
            catch { return null; }
        }

        private static bool CollectionBelongsTo(string json, string accountId)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(accountId)) return false;
                JsonElement data = ReadDataObject(ParseJson(json));
                string creatorId = ReadString(ReadObject(data, "creator"), "id");
                return string.Equals(accountId, creatorId, StringComparison.Ordinal);
            }
            catch { return false; }
        }

        private static IEnumerable<ZhihuCandidate> ParseCandidates(string json)
        {
            JsonElement root = ParseJson(json);
            JsonElement data = ReadObject(root, "data");
            if (data.ValueKind != JsonValueKind.Array)
            {
                data = ReadObject(data, "items");
            }
            if (data.ValueKind != JsonValueKind.Array) yield break;
            int inspected = 0;
            foreach (JsonElement item in data.EnumerateArray())
            {
                if (inspected++ >= 10) yield break;
                JsonElement content = ReadObject(item, "content");
                if (content.ValueKind != JsonValueKind.Object) content = item;
                string type = ReadString(item, "type") ?? ReadString(content, "type");
                string id = ReadString(content, "id") ?? ReadString(item, "id");
                string url;
                string title;
                if (string.Equals(type, "answer", StringComparison.OrdinalIgnoreCase))
                {
                    JsonElement question = ReadObject(content, "question");
                    string questionId = ReadString(question, "id") ?? ReadString(ReadObject(item, "question"), "id");
                    title = ReadString(question, "title") ?? ReadString(item, "title");
                    if (string.IsNullOrWhiteSpace(questionId) || string.IsNullOrWhiteSpace(id)) continue;
                    url = "https://www.zhihu.com/question/" + questionId + "/answer/" + id;
                }
                else if (string.Equals(type, "article", StringComparison.OrdinalIgnoreCase))
                {
                    title = ReadString(content, "title") ?? ReadString(item, "title");
                    if (string.IsNullOrWhiteSpace(id)) continue;
                    url = "https://zhuanlan.zhihu.com/p/" + id;
                }
                else
                {
                    continue;
                }
                if (string.IsNullOrWhiteSpace(title)) title = "知乎" + (type == "answer" ? "回答" : "文章");
                string author = ReadString(ReadObject(content, "author"), "name");
                yield return new ZhihuCandidate
                {
                    CandidateId = type + "-" + id,
                    Title = title,
                    Author = author,
                    Url = url,
                    SourceType = type,
                };
            }
        }

        private static JsonElement ParseJson(string json)
        {
            using (JsonDocument document = JsonDocument.Parse(json))
            {
                return document.RootElement.Clone();
            }
        }

        private static JsonElement ReadDataObject(JsonElement value)
        {
            JsonElement data = ReadObject(value, "data");
            return data.ValueKind == JsonValueKind.Object ? data : value;
        }

        private static JsonElement ReadObject(JsonElement value, string name)
        {
            return value.ValueKind == JsonValueKind.Object && value.TryGetProperty(name, out JsonElement result)
                ? result
                : default(JsonElement);
        }

        private static string ReadString(JsonElement value, string name)
        {
            JsonElement item = ReadObject(value, name);
            if (item.ValueKind == JsonValueKind.String) return item.GetString();
            if (item.ValueKind == JsonValueKind.Number) return item.ToString();
            return null;
        }

        private static bool IsZhihuHost(string host)
        {
            return string.Equals(host, "zhihu.com", StringComparison.OrdinalIgnoreCase)
                || host.EndsWith(".zhihu.com", StringComparison.OrdinalIgnoreCase);
        }

        private sealed class HttpEvidence
        {
            public int StatusCode { get; }
            public string Body { get; }

            public HttpEvidence(int statusCode, string body)
            {
                StatusCode = statusCode;
                Body = body;
            }
        }
    }
}
