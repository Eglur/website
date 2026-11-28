# Eglur Technologies website

The source of [www.eglurtech.com](https://www.eglurtech.com).

Eglur is the workspace for the offices of elected representatives. Clarity for public servants.

- A static site, served by GitHub Pages. No cookies, no analytics and no trackers. Fonts are served from this site (licences in `fonts/OFL-*.txt`).
- Every page shares one stylesheet and one script, `assets/site.css` and `assets/site.js`, and carries a Content-Security-Policy that allows nothing from other sites and no inline code. The one exception: the contact page may also send to the Supabase database that stores messages. Change the `?v=` number in each page when either file changes, so browsers fetch the new version.
- Every page reads in full without JavaScript; the script adds the navigation, the animation, the draft demo and the contact form. The form needs it, and says so when it's turned off.
- How Eglur handles data: [www.eglurtech.com/data](https://www.eglurtech.com/data)
- Security: see [SECURITY.md](SECURITY.md)
- Contact: [www.eglurtech.com/contact](https://www.eglurtech.com/contact). How the form is set up: [tools/contact/SETUP.md](tools/contact/SETUP.md)
