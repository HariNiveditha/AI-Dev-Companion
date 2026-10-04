import { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = 'http://localhost:8000';

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
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');
  
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reqTitle, setReqTitle] = useState('');
  const [reqDesc, setReqDesc] = useState('');

  const fetchProjects = async () => {
    const res = await axios.get(`${API_URL}/projects`);
    setProjects(res.data);
  };

  const createProject = async () => {
    if (!newProjectName) return;
    await axios.post(`${API_URL}/projects`, {
      name: newProjectName,
      description: newProjectDesc,
      language: 'Java',
    });
    setNewProjectName('');
    setNewProjectDesc('');
    fetchProjects();
  };

  const fetchRequirements = async (projectId: string) => {
    const res = await axios.get(`${API_URL}/projects/${projectId}/requirements`);
    setRequirements(res.data);
  };

  const saveRequirement = async () => {
    if (!selectedProjectId || !reqTitle) return;
    await axios.post(`${API_URL}/projects/${selectedProjectId}/requirements`, {
      title: reqTitle,
      description: reqDesc,
    });
    setReqTitle('');
    setReqDesc('');
    fetchRequirements(selectedProjectId);
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      fetchRequirements(selectedProjectId);
    }
  }, [selectedProjectId]);

  return (
    <div style={{ padding: 20, fontFamily: 'sans-serif' }}>
      <h1>AI Software Engineering Assistant</h1>
      <div style={{ display: 'flex', gap: 40 }}>
        <div style={{ flex: 1 }}>
          <h2>Projects</h2>
          <div style={{ marginBottom: 20 }}>
            <input 
              placeholder="Project Name" 
              value={newProjectName} 
              onChange={e => setNewProjectName(e.target.value)} 
            />
            <input 
              placeholder="Description" 
              value={newProjectDesc} 
              onChange={e => setNewProjectDesc(e.target.value)} 
            />
            <button onClick={createProject}>Create Project</button>
          </div>
          <ul>
            {projects.map(p => (
              <li key={p._id} style={{ cursor: 'pointer', fontWeight: p._id === selectedProjectId ? 'bold' : 'normal' }} onClick={() => setSelectedProjectId(p._id)}>
                {p.name} - {p.status}
              </li>
            ))}
          </ul>
        </div>
        
        {selectedProjectId && (
          <div style={{ flex: 1 }}>
            <h2>Project Details</h2>
            <div style={{ marginBottom: 20 }}>
              <h3>Submit Requirement</h3>
              <input 
                placeholder="Requirement Title" 
                value={reqTitle} 
                onChange={e => setReqTitle(e.target.value)} 
                style={{ display: 'block', marginBottom: 10, width: '100%' }}
              />
              <textarea 
                placeholder="Requirement Description" 
                value={reqDesc} 
                onChange={e => setReqDesc(e.target.value)}
                style={{ display: 'block', marginBottom: 10, width: '100%', height: 100 }}
              />
              <button onClick={saveRequirement}>Save Requirement</button>
            </div>
            
            <h3>Requirements</h3>
            <ul>
              {requirements.map(r => (
                <li key={r._id}>
                  <strong>{r.title}</strong>: {r.description} ({r.status})
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
