import { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface Project {
  _id: string;
  name: string;
  description: string;
  language: string;
  status: string;
}

interface Requirement {
  _id: string;
  projectId: string;
  title: string;
  description: string;
  status: string;
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  
  // UI State
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Forms
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');
  
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reqTitle, setReqTitle] = useState('');
  const [reqDesc, setReqDesc] = useState('');

  // Notifications
  const notifyError = (msg: string) => {
    setError(msg);
    setTimeout(() => setError(null), 5000);
  };
  const notifySuccess = (msg: string) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(null), 3000);
  };

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/projects`);
      setProjects(res.data);
    } catch (err) {
      notifyError("Failed to load projects. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const createProject = async () => {
    if (!newProjectName) {
      notifyError("Project name is required.");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_URL}/projects`, {
        name: newProjectName,
        description: newProjectDesc,
        language: 'Java',
      });
      setNewProjectName('');
      setNewProjectDesc('');
      setShowCreateProject(false);
      notifySuccess("Project created successfully.");
      await fetchProjects();
    } catch (err) {
      notifyError("Failed to create project.");
    } finally {
      setLoading(false);
    }
  };

  const fetchRequirements = async (projectId: string) => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/projects/${projectId}/requirements`);
      setRequirements(res.data);
    } catch (err) {
      notifyError("Failed to load requirements.");
    } finally {
      setLoading(false);
    }
  };

  const saveRequirement = async () => {
    if (!selectedProject || !reqTitle || !reqDesc) {
      notifyError("Title and Description are required.");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_URL}/projects/${selectedProject._id}/requirements`, {
        title: reqTitle,
        description: reqDesc,
      });
      setReqTitle('');
      setReqDesc('');
      notifySuccess("Requirement saved successfully.");
      await fetchRequirements(selectedProject._id);
    } catch (err) {
      notifyError("Failed to save requirement.");
    } finally {
      setLoading(false);
    }
  };

  const openProject = (project: Project) => {
    setSelectedProject(project);
    fetchRequirements(project._id);
    setShowCreateProject(false);
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  return (
    <div className="layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2>AI SE Assistant</h2>
        </div>
        <nav className="sidebar-nav">
          <button 
            className={`nav-item ${!selectedProject && !showCreateProject ? 'active' : ''}`} 
            onClick={() => { setSelectedProject(null); setShowCreateProject(false); }}
          >
            Dashboard
          </button>
          <button 
            className={`nav-item ${showCreateProject ? 'active' : ''}`}
            onClick={() => { setShowCreateProject(true); setSelectedProject(null); }}
          >
            + New Project
          </button>
          
          <div className="nav-section">
            <h4>Recent Projects</h4>
            {projects.map(p => (
              <button 
                key={p._id} 
                className={`nav-item sub-item ${selectedProject?._id === p._id ? 'active' : ''}`}
                onClick={() => openProject(p)}
              >
                {p.name}
              </button>
            ))}
          </div>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="header">
          <h1>{selectedProject ? selectedProject.name : showCreateProject ? 'Create Project' : 'Projects Dashboard'}</h1>
          {loading && <span className="loader">Loading...</span>}
        </header>

        {/* Notifications */}
        <div className="notifications">
          {error && <div className="alert error">{error}</div>}
          {success && <div className="alert success">{success}</div>}
        </div>

        <div className="content-body">
          {/* Dashboard View */}
          {!selectedProject && !showCreateProject && (
            <div className="dashboard-view">
              {projects.length === 0 ? (
                <div className="empty-state">
                  <h3>No projects found</h3>
                  <p>Get started by creating your first project.</p>
                  <button className="btn-primary mt-3" onClick={() => setShowCreateProject(true)}>Create Project</button>
                </div>
              ) : (
                <div className="card-grid">
                  {projects.map(p => (
                    <div className="card project-card" key={p._id} onClick={() => openProject(p)}>
                      <h3>{p.name}</h3>
                      <p className="desc">{p.description || 'No description provided.'}</p>
                      <div className="tags">
                        <span className="tag status">{p.status}</span>
                        <span className="tag lang">{p.language}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Create Project View */}
          {showCreateProject && (
            <div className="form-view card">
              <h2>Project Details</h2>
              <div className="form-group">
                <label>Project Name</label>
                <input 
                  type="text" 
                  value={newProjectName} 
                  onChange={e => setNewProjectName(e.target.value)} 
                  placeholder="e.g., Student Management System"
                />
              </div>
              <div className="form-group">
                <label>Description (Optional)</label>
                <textarea 
                  value={newProjectDesc} 
                  onChange={e => setNewProjectDesc(e.target.value)}
                  placeholder="Describe the purpose of this project..."
                />
              </div>
              <div className="form-actions">
                <button className="btn-secondary" onClick={() => setShowCreateProject(false)}>Cancel</button>
                <button className="btn-primary" onClick={createProject} disabled={loading}>Save Project</button>
              </div>
            </div>
          )}

          {/* Project Details View */}
          {selectedProject && (
            <div className="project-view">
              <div className="card project-info">
                <div className="info-header">
                  <h2>Information</h2>
                  <span className="tag status-pill">{selectedProject.status}</span>
                </div>
                <p><strong>Language:</strong> {selectedProject.language}</p>
                <p><strong>Description:</strong> {selectedProject.description}</p>
              </div>

              <div className="card requirements-section mt-4">
                <h2>Requirements</h2>
                
                {requirements.length === 0 ? (
                  <div className="empty-state small">
                    <p>No requirements submitted yet.</p>
                  </div>
                ) : (
                  <ul className="req-list">
                    {requirements.map(r => (
                      <li key={r._id} className="req-item">
                        <div className="req-header">
                          <h4>{r.title}</h4>
                          <span className="tag status">{r.status}</span>
                        </div>
                        <p>{r.description}</p>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="add-req-form mt-4">
                  <h3>Add New Requirement</h3>
                  <div className="form-group">
                    <input 
                      type="text" 
                      placeholder="Requirement Title" 
                      value={reqTitle} 
                      onChange={e => setReqTitle(e.target.value)} 
                    />
                  </div>
                  <div className="form-group">
                    <textarea 
                      placeholder="Requirement Details (e.g., The system should allow users to log in...)" 
                      value={reqDesc} 
                      onChange={e => setReqDesc(e.target.value)}
                    />
                  </div>
                  <button className="btn-primary" onClick={saveRequirement} disabled={loading}>
                    Submit Requirement
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
