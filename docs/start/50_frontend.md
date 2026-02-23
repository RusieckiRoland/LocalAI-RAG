# Frontend development notes

The frontend (`frontend/RAG.html`) is currently a **single-file implementation** for ease of development and testing. It includes inline CSS, JavaScript, and dependencies loaded via CDNs (e.g., TailwindCSS, Highlight.js, Marked.js). This setup allows quick iteration and local testing without build tools, but it is **not production-ready**. For deployment in a production environment, perform the following steps to optimize, secure, and maintain the code:

1. **Separate assets:** Extract inline CSS and JS into separate files (e.g., `styles.css`, `script.js`) for better organization and caching.

2. **Use a bundler:** Integrate a tool like Vite, Parcel, or Webpack to minify assets, bundle dependencies, and eliminate CDNs. This reduces load times and avoids external dependencies.
   - Example: Set up Vite with `vite.config.js` for Tailwind PostCSS integration.

3. **Update dependencies:** Replace outdated CDN versions (e.g., Tailwind 2.2.19, Highlight.js 11.7.0) with the latest stable releases (e.g., Tailwind 3.4+, Highlight.js 11.10+). Use npm/yarn for local installs.

4. **Add security headers:** Implement Content Security Policy (CSP) to restrict script sources. Avoid inline styles/scripts in production to mitigate XSS risks.

5. **Optimize for production:** Remove development-only elements (e.g., debug badges, console logs). Add error handling, accessibility (ARIA attributes), and responsive testing.

6. **Deployment:** Serve via a static file server (e.g., Nginx) with HTTPS. If scaling, consider integrating with a framework like React for more complex features.

Once these changes are applied, the frontend can be treated as production code. For now, open `RAG.html` directly in your browser after starting the backend server.
