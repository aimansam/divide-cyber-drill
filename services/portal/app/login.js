/**
 * OxBlood Login Page Handler
 * Handles authentication for the login page with tabbed interface
 */

const TOKEN_KEY = 'divide_token';

// Tab switching
document.querySelectorAll('.login-tab').forEach(tab => {
  tab.addEventListener('click', function() {
    const platform = this.dataset.platform;
    
    // Don't allow switching to disabled tabs
    if (this.classList.contains('disabled')) {
      return;
    }
    
    // Update active tab
    document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
    this.classList.add('active');
    
    // Update login subtitle and button text
    const subtitle = document.querySelector('.login-subtitle');
    const button = document.getElementById('loginButton');
    
    if (platform === 'drill') {
      subtitle.textContent = 'Sign in to OxBlood Drill';
      button.textContent = 'Sign In to Drill';
    } else if (platform === 'learn') {
      subtitle.textContent = 'Sign in to OxBlood Learn';
      button.textContent = 'Sign In to Learn';
    }
  });
});

// Login form submission
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  const errorDiv = document.getElementById('loginError');
  const loginButton = document.getElementById('loginButton');
  
  // Determine which platform they're logging into
  const activeTab = document.querySelector('.login-tab.active');
  const platform = activeTab ? activeTab.dataset.platform : 'drill';
  
  // Clear previous errors
  errorDiv.classList.remove('show');
  errorDiv.textContent = '';
  
  // Disable button during login
  loginButton.disabled = true;
  loginButton.textContent = 'Signing in...';
  
  try {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sub: username, password })
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Login failed');
    }
    
    const data = await response.json();
    
    // Store token
    localStorage.setItem(TOKEN_KEY, data.token);
    
    // Redirect based on platform
    if (platform === 'drill') {
      window.location.href = '/drill/';
    } else if (platform === 'learn') {
      // For now, redirect to drill since learn is coming soon
      window.location.href = '/drill/';
    }
  } catch (error) {
    console.error('Login error:', error);
    errorDiv.textContent = error.message || 'Login failed. Please check your credentials.';
    errorDiv.classList.add('show');
    
    // Re-enable button
    loginButton.disabled = false;
    loginButton.textContent = 'Sign In to ' + (platform === 'drill' ? 'Drill' : 'Learn');
  }
});

// Check if already logged in — validate token server-side before redirect
// (prevents redirect loop when a stale/expired token is stored)
(function () {
  var existing = null;
  try { existing = localStorage.getItem(TOKEN_KEY); } catch (e) { existing = null; }
  if (!existing) return;
  fetch('/api/v1/me', { headers: { 'X-Divide-Token': existing } }).then(function (resp) {
    if (resp.ok) {
      window.location.href = '/drill/';
    } else if (resp.status === 401) {
      try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    }
  }).catch(function () { /* offline/API down: stay on login page */ });
})();