// #91: offline runtime. support.js looks up window.__resources[url] before loading its CDN scripts; these are
// byte-identical copies of the exact pinned versions (sha384 equals support.js's SRI): react 18.3.1,
// react-dom 18.3.1 (npm "umd" builds), @babel/standalone 7.29.0. Fonts: ./fonts/fonts.css (Geist, Geist Mono).
window.__resources = Object.assign(window.__resources || {}, {
  "https://unpkg.com/react@18.3.1/umd/react.production.min.js": "./vendor/react.production.min.js",
  "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js": "./vendor/react-dom.production.min.js",
  "https://unpkg.com/@babel/standalone@7.29.0/babel.min.js": "./vendor/babel.min.js"
});
