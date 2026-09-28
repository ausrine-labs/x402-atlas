# site-assets

`og.png` is the share image every Atlas page names in its `og:image` and `twitter:image`
(1200×630). `atlas_style.write_assets()` copies it to the site root on every build.
Its source is `og.html`; it carries no numbers, so it never goes stale. To redraw it:

    NODE_PATH=$(npm root -g) node render.js

(`FONT_ROUTE=/path/to/module.js` if Chromium cannot reach Google Fonts from where you run it;
the render refuses to write the image in a fallback face.)
