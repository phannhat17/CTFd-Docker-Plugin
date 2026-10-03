import { defineConfig } from 'vitepress'

// Documentation site for the CTFd Docker containers plugin.
// The markdown lives next to the plugin so GitHub and the site render the same
// files, and there is no second copy to keep in sync.
export default defineConfig({
  title: 'CTFd Containers',
  description:
    'A CTFd plugin that gives every team its own Docker container for a challenge',

  // The plugin itself is not part of the site, so Node has to ignore it when it
  // scans for markdown. Everything under docs/ is published.
  srcExclude: ['**/node_modules/**'],

  // Cloudflare Pages serves from the domain root.
  base: '/',

  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: false,

  head: [
    ['meta', { name: 'theme-color', content: '#0e1117' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: 'CTFd Containers plugin' }],
  ],

  themeConfig: {
    nav: [
      { text: 'Guide', link: '/installation', activeMatch: '^/(installation|configuration|challenges|player-guide)' },
      { text: 'Admin', link: '/admin-console', activeMatch: '^/(admin-console|anti-cheat|import)' },
      { text: 'Operations', link: '/operations', activeMatch: '^/(operations|security|troubleshooting)' },
      { text: 'Compare', link: '/comparison', activeMatch: '^/comparison' },
      { text: 'Changelog', link: '/changelog' },
    ],

    sidebar: [
      {
        text: 'Getting started',
        items: [
          { text: 'Overview', link: '/' },
          { text: 'Installation', link: '/installation' },
          { text: 'Configuration', link: '/configuration' },
        ],
      },
      {
        text: 'Challenges',
        items: [
          { text: 'Creating a challenge', link: '/challenges' },
          { text: 'Subdomain routing', link: '/subdomain-routing' },
          { text: 'Bulk import', link: '/import' },
          { text: 'Player guide', link: '/player-guide' },
        ],
      },
      {
        text: 'Administration',
        items: [
          { text: 'Admin console', link: '/admin-console' },
          { text: 'Anti-cheat', link: '/anti-cheat' },
        ],
      },
      {
        text: 'Running an event',
        items: [
          { text: 'Operations', link: '/operations' },
          { text: 'Security', link: '/security' },
          { text: 'Troubleshooting', link: '/troubleshooting' },
        ],
      },
      {
        text: 'Choosing a plugin',
        items: [{ text: 'Compared with other projects', link: '/comparison' }],
      },
      {
        text: 'Project',
        items: [{ text: 'Changelog', link: '/changelog' }],
      },
    ],

    outline: { level: [2, 3] },

    search: {
      provider: 'local',
    },

    editLink: {
      pattern: 'https://github.com/phannhat17/CTFd-Docker-Plugin/edit/master/docs/:path',
      text: 'Edit this page on GitHub',
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'CTFd Docker Containers Plugin',
    },

    docFooter: {
      prev: 'Previous',
      next: 'Next',
    },

    darkModeSwitchLabel: 'Appearance',
    returnToTopLabel: 'Back to top',
    sidebarMenuLabel: 'Menu',
  },
})
