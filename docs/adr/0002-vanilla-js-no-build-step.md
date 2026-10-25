# Vanilla JavaScript, no build step

The frontend is plain HTML, CSS and JavaScript in `app/static/`, served directly
by FastAPI, with Leaflet and Leaflet.heat vendored. There is no bundler, no
transpiler, no framework and no `node_modules`.

## Why

The app ships as a local desktop-style product to non-technical runners, some of
them disabled or Paralympic athletes who need it to work on whatever machine they
have. A build step turns "clone and run" into "install Node, install a lockfile's
worth of transitive dependencies, build, then run", and it makes a five-year-old
checkout unbuildable when the toolchain moves. Vanilla JS also keeps the DOM
honest: what you see in `index.html` is what the browser parses.

## Consequences

- Every DOM update is imperative; helpers in `app.js` do the templating.
- No JSX, no type checking, no tree shaking. Accept the bundle size.
- Adding a library means vendoring a file and updating third-party notices.
- Accessibility is hand-maintained; it is a review item, not a linter's job.
