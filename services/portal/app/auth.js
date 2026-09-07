/**
 * Authentication Module
 * Handles user authentication, token management, and session state
 */

const TOKEN_KEY = 'divide_token';

class Auth {
  static getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  static setToken(token) {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  }

  static async login(username, password) {
    try {
      const response = await fetch(`/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sub: username, password })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Login failed');
      }

      const data = await response.json();
      this.setToken(data.token);
      return data;
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  }

  static async logout() {
    try {
      await fetch(`/api/v1/auth/logout`, {
        method: 'POST',
        headers: this.getHeaders()
      });
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      this.setToken('');
      window.location.href = '/';
    }
  }

  static async getMe() {
    const token = this.getToken();
    if (!token) return null;

    try {
      const response = await fetch(`/api/v1/me`, {
        headers: this.getHeaders()
      });

      if (!response.ok) {
        if (response.status === 401) {
          this.setToken('');
          return null;
        }
        throw new Error('Failed to fetch user info');
      }

      const user = await response.json();

      // Also fetch database user ID from v2 endpoint
      try {
        const profileResponse = await fetch(`/api/v2/users/me`, {
          headers: this.getHeaders()
        });
        if (profileResponse.ok) {
          const profile = await profileResponse.json();
          user.id = profile.id;
        }
      } catch (e) {
        console.warn('Could not fetch user profile ID:', e);
      }

      return user;
    } catch (error) {
      console.error('Get me error:', error);
      return null;
    }
  }

  static getHeaders() {
    const token = this.getToken();
    return {
      'Content-Type': 'application/json',
      'X-Divide-Token': token
    };
  }

  static isAuthenticated() {
    return !!this.getToken();
  }
}

// Make globally available for non-module scripts
window.Auth = Auth;
window.logout = function() { Auth.logout(); };
