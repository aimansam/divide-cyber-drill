/**
 * UI Drills Module
 * Drill-specific UI methods: play, submit, edit, delete, announcements
 */

Object.assign(UI.prototype, {
  async playDrill(drillId) {
    try {
      const drill = await API.get(`/drills/${drillId}`);
      this.currentDrillId = drillId;
      this.currentDrill = drill;
      
      // Switch to active view
      document.getElementById('drills-list-view').style.display = 'none';
      document.getElementById('drills-active-view').style.display = 'block';
      
      // Populate drill info
      document.getElementById('active-drill-title').textContent = drill.title || 'Untitled Drill';
      document.getElementById('active-drill-description').innerHTML = this.renderMarkdown(drill.description || 'No description');
      document.getElementById('active-drill-status').textContent = drill.status || 'unknown';
      document.getElementById('active-drill-duration').textContent = this.formatDuration(drill.duration_limit_minutes);
      
      // Load all drill data
      this.loadDrillStats(drillId);
      this.loadDrillObjectives(drillId);
      this.loadDrillParticipantsExtended(drillId);
      this.loadDrillScores(drillId);
      this.loadDrillFirstBloods(drillId);
      this.loadDrillSubmissions(drillId);
      this.loadDrillTeams(drillId);
      this.loadDrillAnnouncementsRich(drillId);
      
      // Start timer if drill is active
      if (drill.status === 'active' && drill.started_at) {
        this._startDrillTimer(drill);
      }
    } catch (error) {
      console.error('Failed to load drill:', error);
      this.showToast('Failed to load drill', 'error');
    }
  },

  _startDrillTimer(drill) {
    if (this._drillTimerInterval) clearInterval(this._drillTimerInterval);
    
    const startTime = new Date(drill.started_at).getTime();
    const durationLimit = drill.duration_limit_minutes ? drill.duration_limit_minutes * 60 * 1000 : null;
    
    const updateTimer = () => {
      const now = Date.now();
      const elapsed = Math.floor((now - startTime) / 1000);
      document.getElementById('active-drill-elapsed').textContent = this.formatElapsedTime(elapsed);
      
      if (durationLimit) {
        const remaining = Math.max(0, Math.floor((durationLimit - (now - startTime)) / 1000));
        if (remaining === 0) {
          clearInterval(this._drillTimerInterval);
          this.showToast('Drill time limit reached!', 'warning');
        }
      }
    };
    
    updateTimer();
    this._drillTimerInterval = setInterval(updateTimer, 1000);
  },

  stopDrillAutoRefresh() {
    if (this._drillTimerInterval) {
      clearInterval(this._drillTimerInterval);
      this._drillTimerInterval = null;
    }
  },

  async loadDrillStats(drillId) {
    try {
      const stats = await API.get(`/drills/${drillId}/stats`);
      const statsDiv = document.getElementById('drill-stats');
      if (statsDiv && stats) {
        statsDiv.innerHTML = `
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-md);">
            <div style="text-align: center; padding: var(--space-md); background: var(--bg-tertiary); border-radius: 4px;">
              <div style="font-size: 24px; font-weight: 700; font-family: var(--font-mono);">${stats.total_participants || 0}</div>
              <div style="font-size: 12px; color: var(--text-secondary);">Participants</div>
            </div>
            <div style="text-align: center; padding: var(--space-md); background: var(--bg-tertiary); border-radius: 4px;">
              <div style="font-size: 24px; font-weight: 700; font-family: var(--font-mono);">${stats.correct_submissions || 0}</div>
              <div style="font-size: 12px; color: var(--text-secondary);">Flags Captured</div>
            </div>
          </div>
        `;
      }
    } catch (error) {
      console.error('Failed to load drill stats:', error);
    }
  },

  async loadDrillObjectives(drillId) {
    try {
      const data = await API.get(`/drills/${drillId}/objectives`);
      const objectivesDiv = document.getElementById('drill-objectives');
      if (objectivesDiv && data && data.objectives) {
        if (data.objectives.length === 0) {
          objectivesDiv.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: var(--space-md);">No objectives defined</div>';
        } else {
          objectivesDiv.innerHTML = data.objectives.map(obj => `
            <div style="padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600;">${this.sanitizeHTML(obj.title)}</span>
                <span style="font-family: var(--font-mono); font-weight: 600; color: var(--primary);">${obj.points || 0} pts</span>
              </div>
              ${obj.description ? `<div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">${this.sanitizeHTML(obj.description)}</div>` : ''}
            </div>
          `).join('');
        }
      }
    } catch (error) {
      console.error('Failed to load objectives:', error);
    }
  },

  async loadDrillScores(drillId) {
    try {
      const data = await API.get(`/drills/${drillId}/scores`);
      const scoresDiv = document.getElementById('drill-scores');
      if (scoresDiv && data && data.scores) {
        if (data.scores.length === 0) {
          scoresDiv.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: var(--space-md);">No scores yet</div>';
        } else {
          scoresDiv.innerHTML = data.scores.map((score, idx) => `
            <div style="display: flex; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border);">
              <span style="font-family: var(--font-mono); font-weight: 700; width: 30px;">#${idx + 1}</span>
              <div style="flex: 1;">
                <div style="font-weight: 600;">${score.username || `User ${score.user_id}`}</div>
              </div>
              <span style="font-family: var(--font-mono); font-weight: 600;">${score.points || 0} pts</span>
            </div>
          `).join('');
        }
      }
    } catch (error) {
      console.error('Failed to load scores:', error);
    }
  },

  async loadDrillFirstBloods(drillId) {
    try {
      const data = await API.get(`/drills/${drillId}/first-blood`);
      const firstBloodsDiv = document.getElementById('drill-first-bloods');
      if (firstBloodsDiv && data && data.first_bloods) {
        if (data.first_bloods.length === 0) {
          firstBloodsDiv.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: var(--space-md);">No first bloods yet</div>';
        } else {
          firstBloodsDiv.innerHTML = data.first_bloods.map(fb => `
            <div style="padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600;">${fb.flag_title || `Flag ${fb.flag_id}`}</span>
                <span style="font-size: 12px; color: var(--text-secondary);">${fb.username || `User ${fb.user_id}`}</span>
              </div>
              <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${new Date(fb.solved_at).toLocaleString()}</div>
            </div>
          `).join('');
        }
      }
    } catch (error) {
      console.error('Failed to load first bloods:', error);
    }
  },

  async loadDrillSubmissions(drillId) {
    try {
      const data = await API.get(`/drills/${drillId}/submissions`);
      const submissionsDiv = document.getElementById('drill-submissions');
      if (submissionsDiv && data && data.submissions) {
        if (data.submissions.length === 0) {
          submissionsDiv.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: var(--space-md);">No submissions yet</div>';
        } else {
          submissionsDiv.innerHTML = data.submissions.slice(0, 10).map(sub => `
            <div style="padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600;">${sub.username || `User ${sub.user_id}`}</span>
                <span class="badge badge-${sub.correct ? 'success' : 'danger'}">${sub.correct ? 'Correct' : 'Incorrect'}</span>
              </div>
              <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${new Date(sub.submitted_at).toLocaleString()}</div>
            </div>
          `).join('');
        }
      }
    } catch (error) {
      console.error('Failed to load submissions:', error);
    }
  },

  async submitFlag() {
    const flagInput = document.getElementById('flag-input');
    if (!flagInput) return;
    
    const flagValue = flagInput.value.trim();
    if (!flagValue) {
      this.showToast('Please enter a flag', 'error');
      return;
    }
    
    try {
      this.showToast('Submitting flag...', 'info');
      // Note: This would need the actual flag_id from the drill
      // For now, we'll use a placeholder
      await API.submitFlag(this.currentDrillId, 1, flagValue);
      this.showToast('Flag submitted!', 'success');
      flagInput.value = '';
      // Reload submissions
      this.loadDrillSubmissions(this.currentDrillId);
    } catch (error) {
      console.error('Failed to submit flag:', error);
      this.showToast('Failed to submit flag', 'error');
    }
  },

  async pauseDrill() {
    try {
      await API.post(`/drills/${this.currentDrillId}/pause`, {});
      this.showToast('Drill paused', 'success');
      setTimeout(() => this.playDrill(this.currentDrillId), 500);
    } catch (error) {
      console.error('Failed to pause drill:', error);
      this.showToast('Failed to pause drill', 'error');
    }
  },

  async stopDrill() {
    if (!confirm('Are you sure you want to stop this drill?')) return;
    
    try {
      await API.post(`/drills/${this.currentDrillId}/stop`, {});
      this.showToast('Drill stopped', 'success');
      this.stopDrillAutoRefresh();
      setTimeout(() => this.loadDrills(), 500);
    } catch (error) {
      console.error('Failed to stop drill:', error);
      this.showToast('Failed to stop drill', 'error');
    }
  },

  backToDrillList() {
    this.stopDrillAutoRefresh();
    document.getElementById('drills-list-view').style.display = 'block';
    document.getElementById('drills-active-view').style.display = 'none';
    this.currentDrillId = null;
    this.currentDrill = null;
  },

  async editDrill(drillId) {
    try {
      const drill = await API.get(`/drills/${drillId}`);
      this._editingDrillId = drillId;
      
      // Populate modal with drill data
      document.getElementById('drill-title').value = drill.title || '';
      document.getElementById('drill-description').value = drill.description || '';
      document.getElementById('drill-type').value = drill.drill_type || 'individual';
      document.getElementById('drill-duration').value = drill.duration_limit_minutes || '';
      document.getElementById('drill-max-participants').value = drill.max_participants || '';
      
      // Change modal to edit mode
      const modal = document.getElementById('create-drill-modal');
      const modalTitle = modal.querySelector('.card-title');
      if (modalTitle) modalTitle.textContent = 'Edit Drill';
      const createBtn = modal.querySelector('.btn-primary:last-child');
      if (createBtn) {
        createBtn.textContent = 'Save Changes';
        createBtn.onclick = () => this.saveDrillEdit(drillId);
      }
      
      modal.style.display = 'flex';
    } catch (error) {
      console.error('Failed to load drill for editing:', error);
      this.showToast('Failed to load drill', 'error');
    }
  },

  async saveDrillEdit(drillId) {
    const title = document.getElementById('drill-title').value.trim();
    const description = document.getElementById('drill-description').value.trim();
    const type = document.getElementById('drill-type').value;
    const duration = document.getElementById('drill-duration').value;
    const maxParticipants = document.getElementById('drill-max-participants').value;

    if (!title) {
      this.showToast('Please enter a title', 'error');
      return;
    }

    if (title.length > 200) {
      this.showToast('Title must be 200 characters or less', 'error');
      return;
    }

    if (duration && parseInt(duration) < 0) {
      this.showToast('Duration cannot be negative', 'error');
      return;
    }

    if (maxParticipants && parseInt(maxParticipants) < 0) {
      this.showToast('Max participants cannot be negative', 'error');
      return;
    }

    if (!['individual', 'team'].includes(type)) {
      this.showToast('Invalid drill type', 'error');
      return;
    }

    try {
      this.showToast('Saving changes...', 'info');
      await API.put(`/drills/${drillId}`, {
        title,
        description,
        drill_type: type,
        duration_limit_minutes: duration ? parseInt(duration) : null,
        max_participants: maxParticipants ? parseInt(maxParticipants) : null
      });
      
      this.showToast('Drill updated successfully!', 'success');
      this.hideCreateDrillModal();
      this._editingDrillId = null;
      
      // Reset modal back to create mode
      const modal = document.getElementById('create-drill-modal');
      if (modal) {
        const modalTitle = modal.querySelector('.card-title');
        if (modalTitle) modalTitle.textContent = 'Create New Drill';
        const createBtn = modal.querySelector('.btn-primary:last-child');
        if (createBtn) {
          createBtn.textContent = 'Create Drill';
          createBtn.onclick = () => this.createDrill();
        }
      }
      
      setTimeout(() => this.loadDrills(), 500);
    } catch (error) {
      console.error('Failed to update drill:', error);
      this.showToast('Failed to update drill', 'error');
    }
  },

  async deleteDrill(drillId) {
    if (!confirm('Are you sure you want to delete this drill? This action cannot be undone.')) {
      return;
    }

    try {
      this.showToast('Deleting drill...', 'info');
      await API.delete(`/drills/${drillId}`);
      this.showToast('Drill deleted!', 'success');
      setTimeout(() => this.loadDrills(), 500);
    } catch (error) {
      console.error('Failed to delete drill:', error);
      this.showToast('Failed to delete drill', 'error');
    }
  },

  async addAnnouncement() {
    const text = document.getElementById('announcement-text').value.trim();
    if (!text) {
      this.showToast('Please enter an announcement', 'error');
      return;
    }

    try {
      this.showToast('Posting announcement...', 'info');
      await API.post(`/drills/${this.currentDrillId}/announcements`, {
        title: 'Announcement',
        content: text,
        priority: 'normal'
      });
      this.showToast('Announcement posted!', 'success');
      this.hideAddAnnouncementModal();
      this.loadDrillAnnouncementsRich(this.currentDrillId);
    } catch (error) {
      console.error('Failed to post announcement:', error);
      this.showToast('Failed to post announcement', 'error');
    }
  },

  async loadDrillAnnouncementsRich(drillId) {
    try {
      const data = await API.get(`/drills/${drillId}/announcements`);
      const announcementsDiv = document.getElementById('drill-announcements');
      if (announcementsDiv && data && data.announcements) {
        if (data.announcements.length === 0) {
          announcementsDiv.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: var(--space-md);">No announcements yet</div>';
        } else {
          announcementsDiv.innerHTML = data.announcements.map(ann => `
            <div style="padding: var(--space-md); border-bottom: 1px solid var(--border);">
              <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: var(--space-sm);">
                <div style="flex: 1;">
                  <span style="font-weight: 600;">${this.sanitizeHTML(ann.title || 'Announcement')}</span>
                  <span style="font-size: 12px; color: var(--text-secondary); margin-left: var(--space-md);">${new Date(ann.published_at || ann.created_at).toLocaleString()}</span>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="app.deleteAnnouncement(${drillId}, ${ann.id})" style="color: var(--danger); font-size: 12px; padding: 4px 8px;">Delete</button>
              </div>
              <div style="font-size: 14px; line-height: 1.6;">${this.renderMarkdown(ann.content || '')}</div>
            </div>
          `).join('');
        }
      }
    } catch (error) {
      console.error('Failed to load announcements:', error);
    }
  },

  async deleteAnnouncement(drillId, announcementId) {
    if (!confirm('Are you sure you want to delete this announcement?')) {
      return;
    }

    try {
      this.showToast('Deleting announcement...', 'info');
      await API.delete(`/drills/${drillId}/announcements/${announcementId}`);
      this.showToast('Announcement deleted', 'success');
      await this.loadDrillAnnouncementsRich(drillId);
    } catch (error) {
      console.error('Failed to delete announcement:', error);
      this.showToast('Failed to delete announcement', 'error');
    }
  }
});
