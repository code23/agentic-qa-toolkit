# Responsible use

These tools load web pages and look for problems. Use them only on sites you own or have
clear permission to test.

## What the scripts do to a site

- Load each page you list in a headless browser, one page at a time, with a delay between
  loads. **The page then behaves as it would for any visitor**: it loads its own images,
  scripts and fonts, runs its own JavaScript, and that JavaScript may contact third parties
  or send analytics, including POST requests. The scripts record this traffic; they do not
  block it, because measuring it is the point of the consent check.
- Make their own plain GET requests for pages and source maps.
- Identify themselves with a tagged user agent, so a site owner can see the visits in logs.
- Click one cookie-banner button (Accept or Reject) in a throwaway browser profile, to see
  what the site sets afterwards.

## What they never do

- Type into a page, sign in, or submit a form themselves. The one thing they click is a
  cookie-banner button. What that button's own code then does is up to the site, as it
  would be for any visitor who clicked it: as a backstop the scripts block any page
  navigation that is not a GET, but a site's script can still send data in the background
  or through a GET form.
- Crawl. They visit the URL list you give them and stop.
- Let a page send them to another site. A redirect or navigation of the page itself to a
  host you did not list is blocked and reported as a failed URL. The `www` and bare forms of
  a listed host count as the same site.
- Brute force, fuzz, exploit or scan for vulnerabilities.
- Report to anyone. There is no telemetry.

## What the skills tell an agent to do

The agent is told to stay read-only: look, click through, open and cancel. It may type
obvious test data into a form to check validation, after first checking that the form does
not save as you type, and it never submits. It stops at a payment form, a phone code, an
identity check or a CAPTCHA and asks you.

These are instructions to an AI agent, not technical locks. Supervise the first runs on any
site, give the agent a test account with no real privileges, and prefer staging to
production.

## Evidence can be sensitive

A run folder holds screenshots and page data. On a real site that can include unreleased
work, customer names or personal data. Keep run folders out of version control, treat them
like any other record that may hold personal data, and delete them when you no longer need
them.

The scripts limit what goes into their JSON output: URLs are stored without query strings,
personal email addresses and token-like strings are redacted, and cookie values are never
stored. Role addresses published on a site, such as an info@ address, are kept because
comparing them across pages is one of the checks. Two things are outside that protection: a
screenshot shows whatever was on the screen, and a `--cache` folder holds the raw pages and
exact URLs the script fetched. A cache is working data, not evidence. Keep it out of
anything you share and delete it after the run.

## What a report is not

- Not a penetration test. The security pass is passive.
- Not an accessibility certificate. Automated scans find only part of what a WCAG audit covers.
- Not legal advice. The consent checks show what a site sets and when; whether that is
  lawful where you operate is a question for someone qualified to answer it.
