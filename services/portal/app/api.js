/**
 * API Client Module
 * Handles all HTTP requests to the backend API
 */

const API_BASE = '/api/v2';

class API {
  static async get(endpoint) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      headers: Auth.getHeaders()
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return await response.json();
  }

  static async post(endpoint, data) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: Auth.getHeaders(),
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return await response.json();
  }

  static async put(endpoint, data) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'PUT',
      headers: Auth.getHeaders(),
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new Error(`API error: ${response.status} ${text}`);
    }

    return await response.json();
  }

  static async delete(endpoint) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'DELETE',
      headers: Auth.getHeaders()
    });

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new Error(`API error: ${response.status} ${text}`);
    }

    return await response.json();
  }

  // Dashboard data
  static async getDashboard() {
    const [me, labs, drills] = await Promise.all([
      Auth.getMe(),
      this.get('/labs').catch(() => ({ labs: [] })),
      this.get('/drills').catch(() => ({ drills: [] }))
    ]);

    const allDrills = drills.drills || [];
    const completedDrills = allDrills.filter(d => d.status === 'completed');
    const activeDrills = allDrills.filter(d => d.status === 'active');

    return {
      user: me,
      totalLabs: (labs.labs || []).length,
      completedLabs: completedDrills.length,
      activeDrills: activeDrills.length,
      successRate: allDrills.length > 0 ? Math.round((completedDrills.length / allDrills.length) * 100) : 0,
      teamRank: 2 // Placeholder - would need leaderboard endpoint
    };
  }

  // Labs/Scenarios
  static async getLabs() {
    const labs = await this.get('/labs');
    
    // Category ID to name mapping (since API returns category_id)
    const categoryMap = {
      1: 'Web',
      2: 'Network',
      3: 'Active Directory',
      4: 'Linux',
      5: 'Windows',
      6: 'Forensics',
      7: 'Blue Team'
    };
    
    return (labs.labs || []).map(lab => ({
      id: lab.id,
      title: lab.title || lab.name,
      difficulty: lab.difficulty || 'beginner',
      duration: lab.duration_minutes ? `${lab.duration_minutes} min` : '1h',
      tags: lab.tags || [],
      category: categoryMap[lab.category_id] || 'Web',
      status: 'not_started'
    }));
  }

  // Active drills
  static async getActiveDrills() {
    const drills = await this.get('/drills');
    return (drills.drills || []).filter(d => d.status === 'active');
  }

  // All drills (for history)
  static async getAllDrills() {
    const drills = await this.get('/drills');
    return drills.drills || [];
  }

  // Teams (simplified for v2)
  static async getTeams() {
    return [];
  }

  // Scoreboard (from v2 leaderboard)
  static async getScoreboard() {
    try {
      const leaderboard = await this.get('/leaderboard');
      const entries = leaderboard.leaderboard || [];
      
      // Enrich with user data
      const enriched = await Promise.all(
        entries.map(async (entry) => {
          try {
            const user = await this.get(`/users/${entry.user_id}/profile`);
            return {
              username: user.full_name || user.sub || `User ${entry.user_id}`,
              points: entry.total_points,
              solves: entry.flags_captured,
              time: 'N/A',
              badges: []
            };
          } catch (e) {
            return {
              username: `User ${entry.user_id}`,
              points: entry.total_points,
              solves: entry.flags_captured,
              time: 'N/A',
              badges: []
            };
          }
        })
      );
      return enriched;
    } catch (error) {
      console.error('Get scoreboard error:', error);
      return [];
    }
  }

  // Reports
  static async getReports() {
    const reports = await this.get('/reports');
    return (reports.reports || []).map(report => ({
      id: report.id,
      scenario: report.title || 'Unknown',
      duration: 'N/A',
      result: report.status === 'graded' ? 'Completed' : 'In Progress',
      score: report.quality_score ? Math.round(report.quality_score) : 0
    }));
  }

  // Audit log (for activity feed)
  static async getAuditLog(limit = 20) {
    try {
      return [];
    } catch (error) {
      console.error('Get audit log error:', error);
      return [];
    }
  }

  // Submit flag
  static async submitFlag(runId, flagId, value) {
    return await this.post(`/drills/${runId}/flags/${flagId}`, { value });
  }
}

// Expose globally for classic <script> loading order (auth -> api -> app)
window.API = API;
