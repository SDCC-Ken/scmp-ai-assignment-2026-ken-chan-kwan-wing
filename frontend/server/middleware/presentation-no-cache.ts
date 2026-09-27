/**
 * Presentation pages control a live iframe. Never allow a browser to retain an
 * older controller bundle after the Docker image has been rebuilt.
 */
export default defineEventHandler((event) => {
  const path = getRequestURL(event).pathname
  if (path === '/presentation' || path === '/presenter' || path === '/presentation-login') {
    setResponseHeader(event, 'Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
  }
})
