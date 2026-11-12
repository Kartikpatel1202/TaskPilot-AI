// LOCAL TEST FIXTURE: a YouTube-like page (markup mirrors ytd-video-renderer / a#video-title).
// Controls (query string): login=1 (sign-in gate), captcha=1 (bot check), autoplay=0 (needs a Play click).
// Video ids starting with "blocked" show "Video unavailable".
const VIDEOS = [
  { id: "pyBasics001", title: "Python Tutorial for Beginners - Full Course", channel: "Code Fixture Academy", duration: "4:26:52", views: "41M views", age: "5 years ago" },
  { id: "pyBasics002", title: "Learn Python in 1 Hour", channel: "Fixture Programming", duration: "1:00:06", views: "12M views", age: "3 years ago" },
  { id: "pyAdv000003", title: "Advanced Python Decorators Explained", channel: "Deep Fixture Dev", duration: "18:22", views: "800K views", age: "1 year ago" },
  { id: "lofiBeats04", title: "lofi hip hop radio - beats to relax/study to", channel: "Fixture Lofi", duration: "LIVE", views: "30K watching", age: "" },
  { id: "arijitSong5", title: "Arijit Singh Romantic Songs Jukebox", channel: "Fixture Music India", duration: "52:10", views: "95M views", age: "2 years ago" },
  { id: "arijitSong6", title: "Arijit Singh Live Concert Full", channel: "Fixture Live", duration: "2:01:33", views: "8M views", age: "1 year ago" },
  { id: "jsCrash0007", title: "JavaScript Crash Course for Beginners", channel: "Code Fixture Academy", duration: "1:40:30", views: "6M views", age: "4 years ago" },
  { id: "blockedVid8", title: "Python Region Locked Lecture", channel: "Blocked Fixture", duration: "10:00", views: "1K views", age: "1 month ago" },
  { id: "cookPaneer9", title: "Paneer Butter Masala Recipe", channel: "Fixture Kitchen", duration: "12:45", views: "20M views", age: "6 years ago" },
  { id: "newsDaily10", title: "Daily News Roundup", channel: "Fixture News", duration: "25:00", views: "300K views", age: "1 day ago" },
];

function qs(name) { return new URLSearchParams(location.search).get(name); }
function words(s) { return (s || "").toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 1); }

function gate(text) {
  const main = document.querySelector("main");
  main.innerHTML = `<div class="gate"><h2>${text}</h2><p>Sign in to continue.</p>
    <input type="email" aria-label="Email or phone"><input type="password" aria-label="Enter your password"></div>`;
}

function renderResults() {
  if (qs("login") === "1") return gate("Sign in to confirm you're not a bot");
  if (qs("captcha") === "1") {
    document.querySelector("main").innerHTML = '<div class="gate"><h2>Our systems have detected unusual traffic</h2><div class="g-recaptcha"></div></div>';
    return;
  }
  const q = qs("search_query") || "";
  document.getElementById("search").value = q;
  const terms = words(q);
  const hits = VIDEOS.filter((v) => terms.some((t) => words(v.title + " " + v.channel).includes(t)));
  const main = document.getElementById("contents");
  if (!hits.length) { main.innerHTML = '<p id="no-results">No results found</p>'; return; }
  main.innerHTML = hits.map((v) => `
    <ytd-video-renderer class="style-scope ytd-item-section-renderer">
      <a id="thumbnail" href="watch.html?v=${v.id}"><div class="thumb"><span class="ytd-thumbnail-overlay-time-status-renderer">${v.duration}</span></div></a>
      <div id="meta">
        <a id="video-title" title="${v.title}" href="watch.html?v=${v.id}">${v.title}</a>
        <ytd-channel-name><a href="#">${v.channel}</a></ytd-channel-name>
        <div id="metadata-line"><span class="inline-metadata-item">${v.views}</span><span class="inline-metadata-item">${v.age}</span></div>
      </div>
    </ytd-video-renderer>`).join("");
}

function renderWatch() {
  const id = qs("v") || "";
  const v = VIDEOS.find((x) => x.id === id);
  const main = document.getElementById("watch");
  if (qs("login") === "1") return gate("Sign in to confirm your age");
  if (!v || id.startsWith("blocked") || qs("blocked") === "1") {
    main.innerHTML = '<div class="ytp-error"><div class="ytp-error-content-wrap-reason">Video unavailable</div><p>This video is not available in your country.</p></div>';
    return;
  }
  document.title = v.title + " - YouTube (LOCAL TEST FIXTURE)";
  main.innerHTML = `<div id="movie_player" class="html5-video-player"><video class="html5-main-video" muted playsinline></video></div>
    <button class="ytp-play-button ytp-button" aria-label="Play (k)">Play</button>
    <h1 class="ytd-watch-metadata"><yt-formatted-string>${v.title}</yt-formatted-string></h1>
    <div id="owner"><ytd-channel-name><a href="#">${v.channel}</a></ytd-channel-name></div>`;
  const video = main.querySelector("video");
  const canvas = document.createElement("canvas");
  canvas.width = 320; canvas.height = 180;
  const g = canvas.getContext("2d");
  let frame = 0;
  setInterval(() => { frame++; g.fillStyle = `hsl(${frame % 360},70%,40%)`; g.fillRect(0, 0, 320, 180); g.fillStyle = "#fff"; g.fillText("TEST PATTERN " + frame, 20, 90); }, 50);
  video.srcObject = canvas.captureStream(20);
  const button = main.querySelector(".ytp-play-button");
  const sync = () => { button.setAttribute("aria-label", video.paused ? "Play (k)" : "Pause (k)"); button.textContent = video.paused ? "Play" : "Pause"; };
  video.addEventListener("play", sync); video.addEventListener("pause", sync);
  button.addEventListener("click", () => { if (video.paused) video.play(); else video.pause(); });
  if (qs("autoplay") !== "0") video.play().catch(() => {});
}
