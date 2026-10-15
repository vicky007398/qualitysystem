# Separate customer landing page

`marketing/SolarQMS-Landing.html` is a single standalone HTML file. It embeds its stylesheet, Inter font, logo and product screenshots. Download the file and open it in a browser, or host it separately. Its demo buttons link to the QMS login page.

The QMS app does not render the landing page. Visiting the app while signed out redirects to `/login`; signed-in users keep their dashboard. `/overview` is not an app route.

The user's supplied solar-factory photograph is installed at `static/login-background.webp` and is used as the full-screen login background. The original uploaded PNG remains unchanged under `presentations/`. The background copy is lossless WebP.
