# Manki Cantonese Roadmap Project Notes

This project is for building a learner-facing Cantonese roadmap document based on the YouTube channel **Manki Cantonese**.

## Source Channel

- Channel name: `Manki Cantonese`
- Channel ID: `UC9xosUh_LZUdQv-kw38RehA`
- Channel URL: `https://www.youtube.com/channel/UC9xosUh_LZUdQv-kw38RehA`
- Handle URL: `https://www.youtube.com/@mankicantonese1066`
- Community post with learner testimonials:
  `https://www.youtube.com/post/UgkxyHswgOF12stEDF6iQMOrNd1t-f0uVvNa`

## Working Data Access Methods

The plain `@mankicantonese1066` page may not expose useful text through basic web fetches. Use the channel ID and YouTube's structured page data instead.

### Recent Uploads

Use the YouTube RSS feed for recent videos:

```text
https://www.youtube.com/feeds/videos.xml?channel_id=UC9xosUh_LZUdQv-kw38RehA
```

The RSS feed includes:

- `yt:videoId`
- video title
- watch URL
- publication/update dates
- thumbnail URL
- description
- view/rating metadata when available

Note: RSS only returns recent uploads, not the full historical channel library.

### Playlists

Use the canonical playlist tab:

```text
https://www.youtube.com/channel/UC9xosUh_LZUdQv-kw38RehA/playlists
```

Fetch the HTML and parse the `ytInitialData` JSON:

1. Find `var ytInitialData = `.
2. Read until the following `;</script>`.
3. Parse the substring as JSON.
4. Recursively search for `lockupViewModel` objects where:
   - `contentType` is `LOCKUP_CONTENT_TYPE_PLAYLIST`
   - `contentId` is the playlist ID

Useful fields inside each playlist `lockupViewModel`:

- Title: `metadata.lockupMetadataViewModel.title.content`
- Playlist ID: `contentId`
- Playlist URL: `https://www.youtube.com/playlist?list=<contentId>`
- Thumbnail: `contentImage.collectionThumbnailViewModel.primaryThumbnail.thumbnailViewModel.image.sources[0].url`
- Video-count badge: `contentImage.collectionThumbnailViewModel.primaryThumbnail.thumbnailViewModel.overlays[0].thumbnailOverlayBadgeViewModel.thumbnailBadges[0].thumbnailBadgeViewModel.text`

Verified playlist examples include:

- `Firewatch (Advanced Beginner)`
- `Bear (Absolute Beginner)`
- `Calvin & Hobbes (Beginner)`
- `Choko and Boko (Low Intermediate)`
- `Chibi Maruko Chan (Intermediate)`
- `Is this seat taken? (Beginner)`
- `Random Game (Beginner)`
- `Story Dice (Beginner)`
- `Toem (Beginner)`
- `Work with Me`

### Community Post Testimonials

The community post HTML may not include comments directly, but it exposes a YouTube continuation token for the comments section.

Fetch:

```text
https://www.youtube.com/post/UgkxyHswgOF12stEDF6iQMOrNd1t-f0uVvNa
```

From the page HTML, extract:

- `INNERTUBE_API_KEY`
- `INNERTUBE_CLIENT_VERSION`
- first `continuationCommand.token` for the comments section

Then POST to:

```text
https://www.youtube.com/youtubei/v1/browse?key=<INNERTUBE_API_KEY>
```

Headers:

```text
Content-Type: application/json
x-youtube-client-name: 1
x-youtube-client-version: <INNERTUBE_CLIENT_VERSION>
```

Body:

```json
{
  "context": {
    "client": {
      "clientName": "WEB",
      "clientVersion": "<INNERTUBE_CLIENT_VERSION>",
      "hl": "en",
      "gl": "US"
    }
  },
  "continuation": "<COMMENT_CONTINUATION_TOKEN>"
}
```

The response was verified to include `commentThreadRenderer` objects and `commentEntityPayload` entries. Testimonial text appears at:

```text
payload.commentEntityPayload.properties.content.content
```

The response can also include additional `continuationCommand.token` values for more top-level comments or replies.

## Roadmap Linking Rules

When a testimonial references channel content:

1. Prefer linking to a playlist if a matching playlist exists.
2. Use an individual video link only when no relevant playlist can be identified.
3. Preserve the testimonial's progression path, but clean obvious formatting issues for readability.
4. Categorize referenced content by the difficulty in the playlist title where possible:
   - `Absolute Beginner`
   - `Beginner`
   - `Low Intermediate`
   - `Intermediate`
5. If the difficulty is not inferable from the content title or playlist title, place it in a `To Sort Later` section.

## Google Docs Target

The original draft was created in Google Docs. Keep it as a useful editable/reference draft, but the current shareable artifact is the HTML site described below. Google Drive access was confirmed for:

```text
nick.huttemann@gmail.com
```

Suggested document structure:

- Flashy but professional roadmap title and preamble
- Testimonials / progression paths
- Referenced content tables grouped by difficulty
- To Sort Later section for content whose level is unclear

For the content table, include:

- Thumbnail image
- Content title with hyperlink
- QR code using the same URL

Google Docs supports inserted images, hyperlinks, and tables. QR codes can be generated as image URLs or local image files, then inserted into table cells.

## Current HTML / GitHub Pages Target

The current primary deliverable is a static HTML site:

```text
index.html
```

It is based on `manki-cantonese-roadmap.html`, but `index.html` is the publishable GitHub Pages entry point. The portrait thumbnail is embedded in `index.html` as a base64 data URL so the page can be hosted as a single file. The source image is also kept locally as:

```text
youtube-thumbnail-XEpFiMyknnM.jpg
```

The user preferred the HTML styling over the Google Doc. Continue new visual/layout work in HTML unless the user explicitly asks to return to Google Docs.

### HTML Features

- Default color scheme: `Warm Learning Desk`
- Additional color schemes are available from the top-bar dropdown.
- Light/dark mode toggle is available in the top bar and persists via `localStorage`.
- The first-page hero card includes a circular portrait image using:
  - `object-fit: cover`
  - `object-position: center 34%`
- `Path:` summary boxes and starter-path cards are automatically linkified by the `linkTargets` map in the inline script.
- The content library is generated from the inline `library` array in the script.
- QR codes use QuickChart URLs:

```text
https://quickchart.io/qr?size=360&margin=1&text=<encoded-url>
```

### Local Preview

A local preview server may be running at:

```text
http://127.0.0.1:8765/manki-cantonese-roadmap.html
```

If Python `Start-Process` fails on this Windows machine because of a `Path/PATH` environment issue, use the persistent Node runtime server approach instead. A server was previously started from the project directory with Node's `http` module and served files from:

```text
C:\Users\nickh\Documents\New project
```

The browser may block automated `file://` navigation, so prefer `localhost` / `127.0.0.1` for browser preview checks.

### GitHub Pages

Repository:

```text
https://github.com/NickHEE/manki-cantonese.git
```

Pages URL returned by the GitHub API:

```text
https://nickhee.github.io/manki-cantonese/
```

Pages source was enabled through the GitHub API for:

```text
branch: main
path: /
```

The local git remote is HTTPS:

```text
origin https://github.com/NickHEE/manki-cantonese.git
```

GitHub authentication was set up through Git Credential Manager. Normal `git push` should now work from this repo. If git push fails again, ask the user to refresh GitHub auth rather than switching to SSH by default; SSH was attempted and failed due to no configured GitHub public key.

Only publish files needed for the site unless the user asks otherwise:

- `.gitignore`
- `index.html`
- optionally `youtube-thumbnail-XEpFiMyknnM.jpg` if the image is no longer embedded

Keep project-only notes and drafts local unless requested:

- `AGENTS.md`
- `color-scheme-preview.html`
- `manki-cantonese-roadmap.html`
- `preview-server.*.log`
