(function () {
  const path = window.location.pathname;

  function section() {
    if (path.startsWith('/admin')) return 'owner';
    if (path.startsWith('/cleaner') || path.startsWith('/job-offer')) return 'cleaner';
    if (path.startsWith('/customer') || path.startsWith('/quote') || path.startsWith('/payment-success') || path.startsWith('/review')) return 'customer';
    return 'public';
  }

  const menuSets = {
    public: {
      title: 'Sparkles Cleaning Cambridge',
      eyebrow: 'Smiles Come Standard.',
      items: [
        ['✨', 'Book a clean', 'Start a new booking', '/'],
        ['👤', 'Customer portal', 'View bookings and payments', '/customer'],
        ['🧽', 'Become a Sparkles Cleaner', 'Apply for cleaning work', '/become-a-cleaner'],
        ['🗓️', 'Cleaner portal', 'Assigned jobs and updates', '/cleaner/login'],
        ['🔐', 'Owner login', 'Owner Command Centre', '/admin/login'],
      ],
    },
    customer: {
      title: 'Customer menu',
      eyebrow: 'Bookings and payments',
      items: [
        ['👤', 'My bookings', 'View your booking history', '/customer'],
        ['✨', 'Book another clean', 'Get an instant quote', '/'],
        ['🧽', 'Become a Sparkles Cleaner', 'Apply for flexible work', '/become-a-cleaner'],
        ['↩', 'Log out', 'Sign out of customer portal', '#logout'],
      ],
    },
    cleaner: {
      title: 'Cleaner menu',
      eyebrow: 'Sparkles Cleaner Portal',
      items: [
        ['🧽', 'My jobs', 'Assigned cleaning jobs', '/cleaner/dashboard'],
        ['🔐', 'Cleaner login', 'Sign into your portal', '/cleaner/login'],
        ['✨', 'Booking centre', 'Customer booking page', '/'],
        ['↩', 'Log out', 'Sign out of cleaner portal', '#logout'],
      ],
    },
    owner: {
      title: 'Owner menu',
      eyebrow: 'Command Centre',
      items: [
        ['📊', 'Command Centre', 'Live business overview', '/admin/dashboard'],
        ['📋', 'Bookings', 'Requests, payments and assignment', '/admin/bookings'],
        ['🗓️', 'Calendar', 'Schedule and cleaner availability', '/admin/calendar'],
        ['🧽', 'Cleaners', 'Manage cleaner accounts', '/admin/cleaners'],
        ['🤝', 'Applicants', 'Cleaner recruitment pipeline', '/admin/cleaner-applicants'],
        ['✨', 'AI Recruitment', 'Recruitment assistant', '/admin/ai-recruitment'],
        ['🤖', 'Sparkles AI', 'Automation and office assistant', '/admin/ai-office'],
        ['⚙️', 'Automations', 'Workflow logs and retries', '/admin/automations'],
        ['🏢', 'Setup', 'Business settings', '/admin/setup'],
        ['↩', 'Log out', 'Sign out securely', '#logout'],
      ],
    },
  };

  function getMountPoint() {
    return document.querySelector('.admin-nav, .nav, .sp-nav-inner, header, .header, body');
  }

  async function logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (error) {
      console.warn('Logout request failed', error);
    }
    const current = section();
    if (current === 'owner') window.location.href = '/admin/login';
    else if (current === 'cleaner') window.location.href = '/cleaner/login';
    else window.location.href = '/customer';
  }

  function buildMenu() {
    if (document.querySelector('.sparkles-menu-shell')) return;

    const activeSection = section();
    const config = menuSets[activeSection] || menuSets.public;
    const shell = document.createElement('div');
    shell.className = 'sparkles-menu-shell';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sparkles-menu-button';
    button.setAttribute('aria-haspopup', 'true');
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = '<span>Menu</span><span class="sparkles-menu-caret">⌄</span>';

    const panel = document.createElement('div');
    panel.className = 'sparkles-menu-panel';
    panel.setAttribute('role', 'menu');
    panel.innerHTML = `
      <div class="sparkles-menu-heading">
        <strong>${config.title}</strong>
        <span>${config.eyebrow}</span>
      </div>
      <div class="sparkles-menu-list"></div>
    `;

    const list = panel.querySelector('.sparkles-menu-list');
    config.items.forEach(([icon, label, description, href]) => {
      const isLogout = href === '#logout';
      const element = document.createElement(isLogout ? 'button' : 'a');
      element.className = 'sparkles-menu-link';
      element.setAttribute('role', 'menuitem');
      if (isLogout) {
        element.type = 'button';
        element.addEventListener('click', logout);
      } else {
        element.href = href;
        if (path === href || (href !== '/' && path.startsWith(href))) element.classList.add('active');
      }
      element.innerHTML = `
        <span class="sparkles-menu-icon" aria-hidden="true">${icon}</span>
        <span class="sparkles-menu-text">
          <strong>${label}</strong>
          <span>${description}</span>
        </span>
      `;
      list.appendChild(element);
    });

    button.addEventListener('click', () => {
      const isOpen = shell.classList.toggle('open');
      button.setAttribute('aria-expanded', String(isOpen));
    });

    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) {
        shell.classList.remove('open');
        button.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        shell.classList.remove('open');
        button.setAttribute('aria-expanded', 'false');
      }
    });

    shell.append(button, panel);

    const mount = getMountPoint();
    if (mount === document.body) {
      shell.style.position = 'fixed';
      shell.style.top = '1rem';
      shell.style.right = '1rem';
      document.body.appendChild(shell);
      return;
    }
    mount.appendChild(shell);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildMenu);
  } else {
    buildMenu();
  }
})();
