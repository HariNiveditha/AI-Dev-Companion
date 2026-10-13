import { useState, useEffect } from 'react';
import { useGitRepository } from './components/GitRepository';
import axios from 'axios';
import './App.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

interface Project {
  _id: string;
  name: string;
  description: string;
  language: string;
  status: string;
}

interface RequirementAnalysis {
  functional_requirements: string[];
  non_functional_requirements: string[];
  assumptions: string[];
  ambiguities: string[];
  edge_cases: string[];
  acceptance_criteria: string[];
}

interface Requirement {
  _id: string;
  projectId: string;
  title: string;
  description: string;
  status: string;
  analysis?: RequirementAnalysis;
}

interface CodeArtifact {
  artifact_id: string;
  project_id: string;
  requirement_id: string;
  file_name: string;
  language: 'Java';
  content: string;
  version: number;
  source: 'AI_GENERATED' | 'DEVELOPER_EDITED';
  status: 'AI_GENERATED' | 'EDITED';
  created_at: string;
  updated_at: string;
}

interface TestCase {
  test_case_id: string;
  requirement_id: string;
  title: string;
  description: string;
  input: string;
  expected_output: string;
  priority: string;
  type: string;
  created_at: string;
}

interface CompileResult {
  artifact_id: string;
  status: 'PASSED' | 'FAILED' | 'TOOL_ERROR';
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
  timestamp: string;
}

interface AnalysisFinding {
  tool: 'Checkstyle' | 'SpotBugs' | 'Semgrep';
  severity: string;
  file: string;
  line: number | null;
  column: number | null;
  rule: string | null;
  message: string;
}

interface AnalysisToolResult {
  status: 'COMPLETED' | 'UNAVAILABLE' | 'NOT_RUN' | 'FAILED';
  findings: AnalysisFinding[];
}

interface AnalyzedFile {
  artifact_id: string;
  file_name: string;
  version: number;
}

interface StaticAnalysisResult {
  analysis_id: string;
  artifact_id: string;
  version: number | null;
  analyzed_files: AnalyzedFile[];
  status: 'COMPLETED' | 'PARTIAL' | 'TOOL_ERROR';
  checkstyle: AnalysisToolResult;
  spotbugs: AnalysisToolResult;
  security: AnalysisToolResult;
  created_at: string;
}

interface ExecutionTestResult {
  test_id: string;
  title: string;
  status: 'PASSED' | 'FAILED' | 'ERROR' | 'SKIPPED';
  expected_output: string | null;
  actual_output: string | null;
  error_details: string | null;
  duration_ms: number | null;
  execution_id?: string | null;
  method?: string | null;
  test_case_id?: string | null;
}

interface ExecutionCounts {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
}

interface ExecutionCompileResult {
  status: 'PASSED' | 'FAILED' | 'ERROR';
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number | null;
}

interface ExecutionRun {
  execution_id: string;
  requirement_id: string;
  project_id: string;
  artifact: {
    artifact_id: string;
    project_id: string;
    requirement_id: string;
    file_name: string;
    version: number;
    source: 'AI_GENERATED' | 'DEVELOPER_EDITED' | null;
  };
  status: 'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED' | 'ERROR' | 'SKIPPED' | 'CANCELLED' | 'DISABLED';
  created_at: string;
  updated_at: string;
  test_results: ExecutionTestResult[];
  error_message: string | null;
  requested_test_case_ids?: string[];
  source_snapshot?: {
    artifact_id: string;
    project_id: string;
    requirement_id: string;
    file_name: string;
    version: number;
    source: 'AI_GENERATED' | 'DEVELOPER_EDITED' | null;
  }[];
  executable_test_id?: string | null;
  executable_test_version?: number | null;
  executable_test_class?: string | null;
  counts?: ExecutionCounts;
  compile_result?: ExecutionCompileResult | null;
  runner?: string | null;
  runner_exit_code?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
}

interface ExecutableTest {
  executable_test_id: string;
  project_id: string;
  requirement_id: string;
  class_name: string;
  file_name: string;
  content: string;
  version: number;
  method_map: Record<string, string>;
  source: 'AI_GENERATED' | 'DEVELOPER_EDITED';
  created_at: string;
  updated_at: string;
}

interface CoverageReport {
  total_requirements: number;
  covered_requirements: number;
  uncovered_requirements: string[];
  requirement_coverage_percentage: number;
  total_test_cases: number;
  total_execution_runs: number;
  execution_status: string;
  execution_status_counts: Record<string, number>;
  note: string;
  total_executable_tests?: number;
  test_result_summary?: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    error: number;
    executions_with_results: number;
    scope: string;
  };
  code_coverage?: {
    status: string;
    percentage: number | null;
    reason: string;
  };
  metrics?: Record<string, string>;
  project_id: string | null;
}

type DocumentationType = 'README' | 'JAVA_DOCS' | 'SETUP' | 'API_DOCS';

interface DocumentationRecord {
  documentation_id: string;
  project_id: string;
  document_type: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

interface FindingAssessment {
  finding_id: string;
  classification: 'ACTIONABLE' | 'NON_ACTIONABLE' | 'NEEDS_CONTEXT';
  reasoning: string;
}

interface ImprovementProposal {
  proposal_id: string;
  artifact_id: string;
  project_id: string;
  requirement_id: string;
  file_name: string;
  original_content: string;
  improved_content: string;
  explanation: string;
  findings_addressed: AnalysisFinding[];
  non_actionable_findings: AnalysisFinding[];
  finding_assessments: FindingAssessment[];
  formatting_notes?: string[];
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'NO_CHANGE';
  source_version?: number | null;
  review_comment?: string | null;
  reviewer?: string | null;
  review_action?: 'APPROVE' | 'REJECT' | 'NO_CHANGE' | null;
  decision_timestamp?: string | null;
  compile_result: CompileResult | null;
  after_analysis: StaticAnalysisResult | null;
  accepted_artifact_id: string | null;
  accepted_version: number | null;
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
  rejected_at: string | null;
}

interface ImprovementComparison {
  proposal_id: string;
  original_artifact_id: string;
  original_version: number;
  improved_artifact_id: string | null;
  improved_version: number | null;
  original_analysis: StaticAnalysisResult | null;
  improved_analysis: StaticAnalysisResult | null;
  original_compile_status: string | null;
  improved_compile_status: string | null;
  findings_resolved: AnalysisFinding[];
  findings_remaining: AnalysisFinding[];
  findings_new: AnalysisFinding[];
  findings_unmatched: AnalysisFinding[];
  total_before: number;
  total_after: number;
  created_at: string;
}

const getLatestArtifacts = (artifacts: CodeArtifact[]) => {
  const latest = new Map<string, CodeArtifact>();
  artifacts.forEach(artifact => {
    const current = latest.get(artifact.file_name);
    if (!current || artifact.version > current.version) {
      latest.set(artifact.file_name, artifact);
    }
  });
  return Array.from(latest.values());
};

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
  const [artifactsByRequirement, setArtifactsByRequirement] = useState<Record<string, CodeArtifact[]>>({});
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [draftArtifactContent, setDraftArtifactContent] = useState('');
  const [savingArtifact, setSavingArtifact] = useState(false);
  const [compilingArtifactId, setCompilingArtifactId] = useState<string | null>(null);
  const [compileResults, setCompileResults] = useState<Record<string, CompileResult>>({});
  const [analyzingArtifactId, setAnalyzingArtifactId] = useState<string | null>(null);
  const [analysisResults, setAnalysisResults] = useState<Record<string, StaticAnalysisResult>>({});
  const [generatingTestCasesId, setGeneratingTestCasesId] = useState<string | null>(null);
  const [testCasesByRequirement, setTestCasesByRequirement] = useState<Record<string, TestCase[]>>({});
  const [executionRunsByRequirement, setExecutionRunsByRequirement] = useState<Record<string, ExecutionRun[]>>({});

  // Phase 9: executable JUnit tests + real test execution
  const [executableTestsByRequirement, setExecutableTestsByRequirement] = useState<Record<string, ExecutableTest[]>>({});
  const [selectedExecutableTestId, setSelectedExecutableTestId] = useState<string | null>(null);
  const [executableTestDraft, setExecutableTestDraft] = useState('');
  const [generatingExecutableTestId, setGeneratingExecutableTestId] = useState<string | null>(null);
  const [savingExecutableTestId, setSavingExecutableTestId] = useState<string | null>(null);
  const [runningExecutionId, setRunningExecutionId] = useState<string | null>(null);

  const [coverageReport, setCoverageReport] = useState<CoverageReport | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);

  // Documentation Generation
  const [documentationType, setDocumentationType] =
    useState<DocumentationType>('README');
  const [documentationRecords, setDocumentationRecords] =
    useState<DocumentationRecord[]>([]);
  const [generatedDocumentation, setGeneratedDocumentation] =
    useState<DocumentationRecord | null>(null);
  const [documentationLoading, setDocumentationLoading] = useState(false);

  // AI Code Improvement
  const [improvementProposal, setImprovementProposal] = useState<ImprovementProposal | null>(null);
  const [improvementLoading, setImprovementLoading] = useState(false);
  const [improvementError, setImprovementError] = useState<string | null>(null);
  const [improvementNotice, setImprovementNotice] = useState<string | null>(null);
  const [improvementDiff, setImprovementDiff] = useState<string>('');
  const [improvementComparison, setImprovementComparison] = useState<ImprovementComparison | null>(null);
  const [acceptingProposal, setAcceptingProposal] = useState(false);
  const [rejectingProposal, setRejectingProposal] = useState(false);
  const [proposalHistory, setProposalHistory] = useState<ImprovementProposal[]>([]);
  const [reviewComment, setReviewComment] = useState<string>('');
  const [confirmAction, setConfirmAction] = useState<'APPROVE' | 'REJECT' | null>(null);
  const [expandedFindings, setExpandedFindings] = useState<Record<string, boolean>>({});

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
      await Promise.all(res.data
        .filter((requirement: Requirement) => requirement.status === 'CONFIRMED')
        .map(async (requirement: Requirement) => {
          const artifactRes = await axios.get(`${API_URL}/requirements/${requirement._id}/artifacts`);
          setArtifactsByRequirement(current => ({ ...current, [requirement._id]: artifactRes.data }));
          try {
            const executionRes = await axios.get(`${API_URL}/requirements/${requirement._id}/executions`);
            setExecutionRunsByRequirement(current => ({ ...current, [requirement._id]: executionRes.data }));
          } catch {
            setExecutionRunsByRequirement(current => ({ ...current, [requirement._id]: [] }));
          }
          await fetchExecutableTests(requirement._id);
        }));
    } catch (err) {
      notifyError("Failed to load requirements.");
    } finally {
      setLoading(false);
    }
  };

  const generateCode = async (requirement: Requirement) => {
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/requirements/${requirement._id}/generate-code`);
      setArtifactsByRequirement(current => ({
        ...current,
        [requirement._id]: [...(current[requirement._id] || []), ...res.data],
      }));
      notifySuccess("Java source generated successfully.");
    } catch (err: any) {
      if (!err.response) {
        notifyError("Backend unavailable. Start the API and try again.");
      } else {
        notifyError(
          err.response.data?.detail ||
          `Code generation failed (HTTP ${err.response.status}).`,
        );
      }
    } finally {
      setLoading(false);
    }
  };

  const selectArtifact = (artifact: CodeArtifact) => {
    setSelectedArtifactId(artifact.artifact_id);
    setDraftArtifactContent(artifact.content);
    setReviewComment('');
    setConfirmAction(null);
    fetchProposalHistory(artifact.artifact_id);
  };

  const fetchProposalHistory = async (artifactId: string) => {
    try {
      const res = await axios.get<ImprovementProposal[]>(`${API_URL}/improvements?artifact_id=${artifactId}`);
      setProposalHistory(res.data);
      if (res.data.length > 0) {
        const latest = res.data[0];
        setImprovementProposal(latest);
        if (latest.status !== 'NO_CHANGE') {
          try {
            const diffRes = await axios.get(`${API_URL}/improvements/${latest.proposal_id}/diff`);
            setImprovementDiff(diffRes.data.diff);
          } catch {
            setImprovementDiff('');
          }
        } else {
          setImprovementDiff('');
        }
        if (latest.status === 'ACCEPTED') {
          try {
            const compRes = await axios.get(`${API_URL}/improvements/${latest.proposal_id}/comparison`);
            setImprovementComparison(compRes.data);
          } catch {
            setImprovementComparison(null);
          }
        } else {
          setImprovementComparison(null);
        }
      } else {
        setImprovementProposal(null);
        setImprovementDiff('');
        setImprovementComparison(null);
      }
    } catch {
      setProposalHistory([]);
    }
  };

  const selectProposal = async (proposal: ImprovementProposal) => {
    setImprovementProposal(proposal);
    setReviewComment('');
    setConfirmAction(null);
    if (proposal.status !== 'NO_CHANGE') {
      try {
        const diffRes = await axios.get(`${API_URL}/improvements/${proposal.proposal_id}/diff`);
        setImprovementDiff(diffRes.data.diff);
      } catch {
        setImprovementDiff('');
      }
    } else {
      setImprovementDiff('');
    }
    if (proposal.status === 'ACCEPTED') {
      try {
        const compRes = await axios.get(`${API_URL}/improvements/${proposal.proposal_id}/comparison`);
        setImprovementComparison(compRes.data);
      } catch {
        setImprovementComparison(null);
      }
    } else {
      setImprovementComparison(null);
    }
  };

  const saveArtifact = async (artifact: CodeArtifact) => {
    if (!draftArtifactContent.trim()) {
      notifyError("Code content cannot be empty.");
      return;
    }
    setSavingArtifact(true);
    try {
      const res = await axios.put(`${API_URL}/artifacts/${artifact.artifact_id}`, {
        content: draftArtifactContent,
      });
      setArtifactsByRequirement(current => ({
        ...current,
        [artifact.requirement_id]: [...(current[artifact.requirement_id] || []), res.data],
      }));
      setSelectedArtifactId(res.data.artifact_id);
      setDraftArtifactContent(res.data.content);
      notifySuccess(`Saved ${res.data.file_name} version ${res.data.version}.`);
    } catch (err: any) {
      notifyError(err.response?.data?.detail || "Failed to save code artifact.");
    } finally {
      setSavingArtifact(false);
    }
  };

  const compileArtifact = async (artifact: CodeArtifact) => {
    setCompilingArtifactId(artifact.artifact_id);
    try {
      const res = await axios.post(`${API_URL}/artifacts/${artifact.artifact_id}/compile`);
      setCompileResults(current => ({ ...current, [artifact.artifact_id]: res.data }));
      if (res.data.status === 'PASSED') {
        notifySuccess(`BUILD PASSED in ${res.data.duration_ms} ms.`);
      } else {
        notifyError(`BUILD ${res.data.status}: ${res.data.stderr || 'See compiler output below.'}`);
      }
    } catch (err: any) {
      if (err.response?.data?.status) {
        const result = err.response.data as CompileResult;
        setCompileResults(current => ({ ...current, [artifact.artifact_id]: result }));
        notifyError(result.stderr || `Compilation tool error (HTTP ${err.response.status}).`);
      } else if (!err.response) {
        notifyError("Backend unavailable. Start the API and try again.");
      } else {
        notifyError(err.response.data?.detail || `Compilation failed (HTTP ${err.response.status}).`);
      }
    } finally {
      setCompilingArtifactId(null);
    }
  };

  const analyzeArtifact = async (artifact: CodeArtifact) => {
    setAnalyzingArtifactId(artifact.artifact_id);
    try {
      const res = await axios.post(`${API_URL}/artifacts/${artifact.artifact_id}/analyze`);
      setAnalysisResults(current => ({ ...current, [artifact.artifact_id]: res.data }));
      notifySuccess("Static and security analysis completed.");
    } catch (err: any) {
      if (!err.response) {
        notifyError("Backend unavailable. Start the API and try again.");
      } else {
        notifyError(err.response.data?.detail || `Analysis failed (HTTP ${err.response.status}).`);
      }
    } finally {
      setAnalyzingArtifactId(null);
    }
  };

  const generateTestCases = async (requirement: Requirement) => {
    if (requirement.status !== 'CONFIRMED') {
      notifyError("Requirement must be confirmed before generating test cases.");
      return;
    }

    setGeneratingTestCasesId(requirement._id);
    try {
      const res = await axios.post(`${API_URL}/requirements/${requirement._id}/generate-test-cases`);
      setTestCasesByRequirement(current => ({
        ...current,
        [requirement._id]: res.data,
      }));
      notifySuccess("Test cases generated successfully.");
    } catch (err: any) {
      if (!err.response) {
        notifyError("Backend unavailable. Start the API and try again.");
      } else {
        notifyError(err.response.data?.detail || `Test case generation failed (HTTP ${err.response.status}).`);
      }
    } finally {
      setGeneratingTestCasesId(null);
    }
  };

  const fetchExecutableTests = async (requirementId: string) => {
    try {
      const res = await axios.get<ExecutableTest[]>(
        `${API_URL}/requirements/${requirementId}/executable-tests`
      );
      setExecutableTestsByRequirement(current => ({
        ...current,
        [requirementId]: res.data,
      }));
      const latest = res.data[res.data.length - 1];
      if (latest) {
        setSelectedExecutableTestId(latest.executable_test_id);
        setExecutableTestDraft(latest.content);
      }
    } catch {
      setExecutableTestsByRequirement(current => ({
        ...current,
        [requirementId]: [],
      }));
    }
  };

  const generateExecutableTest = async (requirement: Requirement) => {
    const cases = testCasesByRequirement[requirement._id] || [];
    if (cases.length === 0) {
      notifyError("Generate descriptive test cases first - an executable JUnit test implements them.");
      return;
    }

    setGeneratingExecutableTestId(requirement._id);
    try {
      const res = await axios.post<ExecutableTest>(
        `${API_URL}/requirements/${requirement._id}/executable-tests/generate`,
        { test_case_ids: cases.map(testCase => testCase.test_case_id) },
      );
      setExecutableTestsByRequirement(current => ({
        ...current,
        [requirement._id]: [...(current[requirement._id] || []), res.data],
      }));
      setSelectedExecutableTestId(res.data.executable_test_id);
      setExecutableTestDraft(res.data.content);
      notifySuccess(`Executable JUnit test generated (${res.data.class_name}).`);
    } catch (err: any) {
      if (!err.response) {
        notifyError("Backend unavailable. Start the API and try again.");
      } else {
        notifyError(
          err.response?.data?.detail ||
            `Executable test generation failed (HTTP ${err.response?.status}).`,
        );
      }
    } finally {
      setGeneratingExecutableTestId(null);
    }
  };

  const saveExecutableTest = async (requirement: Requirement) => {
    if (!executableTestDraft.trim()) {
      notifyError("Test source cannot be empty.");
      return;
    }
    const current = (executableTestsByRequirement[requirement._id] || []).find(
      test => test.executable_test_id === selectedExecutableTestId,
    );
    const methodMap = current?.method_map || {};

    setSavingExecutableTestId(requirement._id);
    try {
      const res = await axios.post<ExecutableTest>(
        `${API_URL}/requirements/${requirement._id}/executable-tests`,
        { content: executableTestDraft, method_map: methodMap },
      );
      setExecutableTestsByRequirement(current => ({
        ...current,
        [requirement._id]: [...(current[requirement._id] || []), res.data],
      }));
      setSelectedExecutableTestId(res.data.executable_test_id);
      notifySuccess(`Saved ${res.data.file_name} version ${res.data.version}.`);
    } catch (err: any) {
      notifyError(
        err.response?.data?.detail || "Failed to save executable test.",
      );
    } finally {
      setSavingExecutableTestId(null);
    }
  };

  const runTests = async (requirement: Requirement) => {
    const selected = (executableTestsByRequirement[requirement._id] || []).find(
      test => test.executable_test_id === selectedExecutableTestId,
    );
    if (!selected) {
      notifyError("Generate or select an executable JUnit test first.");
      return;
    }

    const latestArtifacts = artifactsByRequirement[requirement._id] || [];
    const latestArtifact = getLatestArtifacts(latestArtifacts)[0];
    if (!latestArtifact) {
      notifyError("Generate and save a Java artifact before running tests.");
      return;
    }

    // Prevent accidental concurrent runs from repeated clicks.
    setRunningExecutionId(requirement._id);
    try {
      const res = await axios.post<ExecutionRun>(
        `${API_URL}/requirements/${requirement._id}/executions`,
        {
          artifact_id: latestArtifact.artifact_id,
          test_case_ids: Object.keys(selected.method_map),
          executable_test_id: selected.executable_test_id,
        },
      );
      setExecutionRunsByRequirement(current => ({
        ...current,
        [requirement._id]: [res.data, ...(current[requirement._id] || [])],
      }));

      const counts = res.data.counts;
      if (res.data.status === 'PASSED') {
        notifySuccess(`Tests passed: ${counts?.passed ?? 0}/${counts?.total ?? 0}.`);
      } else if (res.data.status === 'FAILED') {
        notifyError(
          `Tests failed: ${counts?.failed ?? 0} of ${counts?.total ?? 0}. See results below.`,
        );
      } else if (res.data.status === 'DISABLED' || res.data.status === 'ERROR') {
        notifyError(res.data.error_message || `Execution ${res.data.status}.`);
      } else {
        notifySuccess(`Execution ${res.data.status}.`);
      }
    } catch (err: any) {
      notifyError(
        err.response?.data?.detail ||
          `Test execution failed (HTTP ${err.response?.status}).`,
      );
    } finally {
      setRunningExecutionId(null);
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

  const fetchCoverageReport = async (projectId: string) => {
    setCoverageLoading(true);

    try {
      const response = await axios.get<CoverageReport>(
        `${API_URL}/reports/coverage`,
        { params: { project_id: projectId } },
      );

      setCoverageReport(response.data);
    } catch {
      setCoverageReport(null);
      notifyError('Failed to load the coverage report.');
    } finally {
      setCoverageLoading(false);
    }
  };

  const fetchDocumentation = async (projectId: string) => {
    try {
      const response = await axios.get(
        `${API_URL}/documentation/${projectId}`,
      );

      const records: DocumentationRecord[] =
        response.data.documentation || [];

      setDocumentationRecords(records);
      setGeneratedDocumentation(records[0] || null);
    } catch {
      setDocumentationRecords([]);
      setGeneratedDocumentation(null);
    }
  };

  const generateDocumentation = async () => {
    if (!selectedProject) {
      notifyError('Please select a project first.');
      return;
    }

    setDocumentationLoading(true);

    try {
      const response = await axios.post(
        `${API_URL}/documentation/generate`,
        {
          project_id: selectedProject._id,
          document_type: documentationType,
        },
      );

      const documentation: DocumentationRecord =
        response.data.documentation;

      if (!documentation) {
        throw new Error('The API returned no documentation.');
      }

      setGeneratedDocumentation(documentation);

      setDocumentationRecords(current => [
        documentation,
        ...current.filter(
          item => item.documentation_id !== documentation.documentation_id,
        ),
      ]);

      notifySuccess('Documentation generated successfully.');
    } catch (err: any) {
      notifyError(
        err.response?.data?.detail ||
        err.message ||
        'Failed to generate documentation.',
      );
    } finally {
      setDocumentationLoading(false);
    }
  };

  const generateImprovement = async (artifact: CodeArtifact) => {
    setImprovementLoading(true);
    setImprovementError(null);
    setImprovementNotice(null);
    setImprovementProposal(null);
    setImprovementDiff('');
    setImprovementComparison(null);
    setReviewComment('');
    setConfirmAction(null);

    try {
      const response = await axios.post(
        `${API_URL}/improvements/generate?artifact_id=${artifact.artifact_id}`
      );
      const proposal: ImprovementProposal = response.data;
      setImprovementProposal(proposal);

      await fetchProposalHistory(artifact.artifact_id);

      if (proposal.status === 'NO_CHANGE') {
        // Valid review, no safe source change: informational, not an error.
        // Verdicts render in the proposal panel below; no diff to fetch.
        setImprovementNotice('Review completed — no source change recommended.');
        return;
      }

      // Fetch the diff
      const diffResponse = await axios.get(
        `${API_URL}/improvements/${proposal.proposal_id}/diff`
      );
      setImprovementDiff(diffResponse.data.diff);

      notifySuccess('Improvement proposal generated successfully.');
    } catch (err: any) {
      if (!err.response) {
        notifyError('Backend unavailable. Start the API and try again.');
      } else {
        notifyError(
          err.response.data?.detail ||
            `Improvement generation failed (HTTP ${err.response.status}).`
        );
      }
    } finally {
      setImprovementLoading(false);
    }
  };

  const acceptProposal = async (proposal: ImprovementProposal) => {
    setAcceptingProposal(true);
    setImprovementError(null);
    setImprovementNotice(null);

    try {
      const response = await axios.post(
        `${API_URL}/improvements/${proposal.proposal_id}/accept`,
        {
          comment: reviewComment.trim() || undefined,
          reviewer: 'local-developer',
        }
      );
      const updatedProposal: ImprovementProposal = response.data;
      setImprovementProposal(updatedProposal);
      setReviewComment('');
      setConfirmAction(null);

      // Refresh the authoritative artifact list from MongoDB so the
      // Files and Versions panels immediately show the newly accepted
      // version.  fetchRequirements replaces the array for the
      // requirement, so no duplicates are introduced.
      if (selectedProject) {
        try {
          await fetchRequirements(selectedProject._id);
        } catch {
          // The acceptance itself succeeded; a stale panel is better
          // than falsely reporting failure.
        }
      }

      // Refresh proposal history
      await fetchProposalHistory(proposal.artifact_id);

      // Fetch comparison
      const comparisonResponse = await axios.get(
        `${API_URL}/improvements/${proposal.proposal_id}/comparison`
      );
      setImprovementComparison(comparisonResponse.data);

      notifySuccess('Changes approved & accepted. New artifact version created and verified.');
    } catch (err: any) {
      if (!err.response) {
        notifyError('Backend unavailable. Start the API and try again.');
      } else {
        notifyError(
          err.response.data?.detail ||
            `Accept failed (HTTP ${err.response.status}).`
        );
      }
    } finally {
      setAcceptingProposal(false);
    }
  };

  const rejectProposal = async (proposal: ImprovementProposal) => {
    setRejectingProposal(true);
    setImprovementError(null);
    setImprovementNotice(null);

    try {
      const response = await axios.post(
        `${API_URL}/improvements/${proposal.proposal_id}/reject`,
        {
          comment: reviewComment.trim() || undefined,
          reviewer: 'local-developer',
        }
      );
      const updatedProposal: ImprovementProposal = response.data;
      setImprovementProposal(updatedProposal);
      setReviewComment('');
      setConfirmAction(null);

      // Refresh proposal history
      await fetchProposalHistory(proposal.artifact_id);

      notifySuccess('Proposal rejected. Original artifact preserved.');
    } catch (err: any) {
      if (!err.response) {
        notifyError('Backend unavailable. Start the API and try again.');
      } else {
        notifyError(
          err.response.data?.detail ||
            `Reject failed (HTTP ${err.response.status}).`
        );
      }
    } finally {
      setRejectingProposal(false);
    }
  };

  const openProject = (project: Project) => {
    setSelectedProject(project);
    setCoverageReport(null);
    setGeneratedDocumentation(null);
    fetchRequirements(project._id);
    fetchCoverageReport(project._id);
    fetchDocumentation(project._id);
    setShowCreateProject(false);
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const git = useGitRepository(selectedProject?._id || null, {
    onSuccess: notifySuccess,
    onError: notifyError,
  });

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
          <button
            className={`nav-item ${selectedProject ? 'active' : ''}`}
            onClick={() => { setShowCreateProject(false); setSelectedProject(null); }}>
            Git Repository
          </button>
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

              {/* Coverage & Quality Report */}
              <div className="card coverage-report mt-4">
                <div className="coverage-report-header">
                  <div>
                    <h2>Coverage &amp; Quality Report</h2>
                    <p>Requirement-to-test-case linkage and real test execution results. Java source-code coverage is not measured.</p>
                  </div>
                  <button
                    className="btn-secondary"
                    onClick={() => fetchCoverageReport(selectedProject._id)}
                    disabled={coverageLoading}
                  >
                    {coverageLoading ? 'Refreshing...' : 'Refresh Report'}
                  </button>
                </div>

                {coverageLoading && !coverageReport ? (
                  <p className="loader">Loading coverage report...</p>
                ) : coverageReport ? (
                  <>
                    <div className="coverage-metrics">
                      <div className="coverage-metric">
                        <span>Requirement Coverage (linkage)</span>
                        <strong>{coverageReport.requirement_coverage_percentage}%</strong>
                      </div>

                      <div className="coverage-metric">
                        <span>Covered Requirements</span>
                        <strong>
                          {coverageReport.covered_requirements}/
                          {coverageReport.total_requirements}
                        </strong>
                      </div>

                      <div className="coverage-metric">
                        <span>Total Test Cases</span>
                        <strong>{coverageReport.total_test_cases}</strong>
                      </div>

                      <div className="coverage-metric">
                        <span>Execution Runs</span>
                        <strong>{coverageReport.total_execution_runs}</strong>
                      </div>

                      {coverageReport.test_result_summary ? (
                        <div className="coverage-metric">
                          <span>Test Results (all runs)</span>
                          <strong>
                            {coverageReport.test_result_summary.passed}✓ / {coverageReport.test_result_summary.failed}✗ / {coverageReport.test_result_summary.skipped}– / {coverageReport.test_result_summary.error}!
                          </strong>
                        </div>
                      ) : null}

                      <div className="coverage-metric">
                        <span>Code Coverage</span>
                        <strong>Not measured</strong>
                      </div>
                    </div>

                    <div
                      className="coverage-progress-track"
                      role="progressbar"
                      aria-label="Requirement coverage"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={coverageReport.requirement_coverage_percentage}
                    >
                      <div
                        className="coverage-progress-fill"
                        style={{
                          width: `${Math.max(
                            0,
                            Math.min(100, coverageReport.requirement_coverage_percentage),
                          )}%`,
                        }}
                      />
                    </div>

                    <p className="coverage-note">{coverageReport.note}</p>

                    {coverageReport.code_coverage ? (
                      <p className="coverage-note">
                        <strong>Code coverage:</strong> {coverageReport.code_coverage.reason}
                      </p>
                    ) : null}

                    <div className="coverage-details">
                      <section>
                        <h3>Uncovered Requirements</h3>

                        {coverageReport.uncovered_requirements.length === 0 ? (
                          <p className="coverage-success">
                            All requirements have at least one linked test case.
                          </p>
                        ) : (
                          <ul className="coverage-uncovered-list">
                            {coverageReport.uncovered_requirements.map(requirementId => {
                              const requirement = requirements.find(
                                item => item._id === requirementId,
                              );

                              return (
                                <li key={requirementId}>
                                  <strong>
                                    {requirement?.title || requirementId}
                                  </strong>
                                  {!requirement && (
                                    <span className="coverage-id">
                                      {requirementId}
                                    </span>
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        )}
                      </section>

                      <section>
                        <h3>Execution Status Breakdown</h3>

                        {Object.keys(coverageReport.execution_status_counts).length === 0 ? (
                          <p className="code-empty">No execution runs recorded.</p>
                        ) : (
                          <ul className="coverage-status-list">
                            {Object.entries(coverageReport.execution_status_counts)
                              .sort(([a], [b]) => a.localeCompare(b))
                              .map(([status, count]) => (
                                <li key={status}>
                                  <span className="tag status">{status}</span>
                                  <strong>{count}</strong>
                                </li>
                              ))}
                          </ul>
                        )}
                      </section>
                    </div>
                  </>
                ) : (
                  <p className="code-empty">
                    The coverage report could not be loaded. Check that the backend is
                    running, then refresh the report.
                  </p>
                )}
              </div>

              {/* Documentation Generation */}
              <div className="card mt-4 documentation-section">
                <div className="coverage-report-header">
                  <div>
                    <h2>Documentation Generation</h2>
                    <p>
                      Generate project documentation from your saved Java source files.
                    </p>
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor="documentation-type">Documentation Type</label>
                  <select
                    id="documentation-type"
                    value={documentationType}
                    onChange={event =>
                      setDocumentationType(event.target.value as DocumentationType)
                    }
                  >
                    <option value="README">README</option>
                    <option value="JAVA_DOCS">Java Documentation</option>
                    <option value="SETUP">Setup Guide</option>
                    <option value="API_DOCS">API Documentation</option>
                  </select>
                </div>

                <button
                  className="btn-primary mt-3"
                  onClick={generateDocumentation}
                  disabled={documentationLoading}
                >
                  {documentationLoading
                    ? 'Generating Documentation...'
                    : 'Generate Documentation'}
                </button>

                {generatedDocumentation && (
                  <div className="generated-documentation mt-4">
                    <div className="coverage-report-header">
                      <div>
                        <h3>{generatedDocumentation.title}</h3>
                        <p>
                          Type: {generatedDocumentation.document_type}
                        </p>
                      </div>
                      <button
                        className="btn-secondary"
                        onClick={() => {
                          const blob = new Blob(
                            [generatedDocumentation.content],
                            { type: 'text/markdown;charset=utf-8' },
                          );
                          const url = URL.createObjectURL(blob);
                          const link = document.createElement('a');

                          link.href = url;
                          link.download = `${generatedDocumentation.document_type.toLowerCase()}.md`;
                          link.click();

                          URL.revokeObjectURL(url);
                        }}
                      >
                        Download Markdown
                      </button>
                    </div>

                    <textarea
                      className="documentation-content"
                      value={generatedDocumentation.content}
                      readOnly
                      rows={18}
                      aria-label="Generated documentation"
                    />
                  </div>
                )}

                {!generatedDocumentation && !documentationLoading && (
                  <p className="code-empty mt-3">
                    No documentation generated yet. Select a document type and click
                    Generate Documentation.
                  </p>
                )}

                {documentationRecords.length > 0 && (
                  <div className="mt-4">
                    <h3>Previously Generated Documentation</h3>

                    <div className="action-group">
                      {documentationRecords.map(record => (
                        <button
                          key={record.documentation_id}
                          className="btn-secondary"
                          onClick={() => setGeneratedDocumentation(record)}
                        >
                          {record.title}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
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
                        
                        {(r.status === 'DRAFT' || r.status === 'ANALYSIS_FAILED') && (
                          <button className="btn-primary mt-3" onClick={async () => {
                            setLoading(true);
                            try {
                              await axios.post(`${API_URL}/requirements/${r._id}/analyze`);
                              notifySuccess("Analysis complete!");
                              await fetchRequirements(selectedProject._id);
                            } catch (err: any) {
                              notifyError(err.response?.data?.detail || "Analysis failed");
                              await fetchRequirements(selectedProject._id); // Update status to FAILED
                            } finally {
                              setLoading(false);
                            }
                          }} disabled={loading}>Analyze Requirement</button>
                        )}

                        {r.status === 'ANALYZING' && (
                          <div className="mt-3 loader">Analyzing requirement with AI...</div>
                        )}

                        {r.analysis && (
                          <div className="analysis-results mt-3">
                            <h4>AI Requirement Analysis</h4>
                            <div className="analysis-section">
                              <h5>Functional Requirements</h5>
                              <ul>{r.analysis.functional_requirements.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>
                            <div className="analysis-section">
                              <h5>Non-Functional Requirements</h5>
                              <ul>{r.analysis.non_functional_requirements.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>
                            <div className="analysis-section">
                              <h5>Assumptions</h5>
                              <ul>{r.analysis.assumptions.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>
                            <div className="analysis-section">
                              <h5>Ambiguities</h5>
                              <ul>{r.analysis.ambiguities.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>
                            <div className="analysis-section">
                              <h5>Edge Cases</h5>
                              <ul>{r.analysis.edge_cases.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>
                            <div className="analysis-section">
                              <h5>Acceptance Criteria</h5>
                              <ul>{r.analysis.acceptance_criteria.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                            </div>

                            {r.status === 'ANALYZED' && (
                              <button className="btn-success mt-3" onClick={async () => {
                                setLoading(true);
                                try {
                                  await axios.post(`${API_URL}/requirements/${r._id}/confirm`);
                                  notifySuccess("Requirement confirmed!");
                                  await fetchRequirements(selectedProject._id);
                                } catch (err) {
                                  notifyError("Failed to confirm requirement.");
                                } finally {
                                  setLoading(false);
                                }
                              }} disabled={loading}>Confirm Requirement</button>
                            )}
                          </div>
                        )}

                        {r.status === 'CONFIRMED' && (() => {
                          const requirementArtifacts = artifactsByRequirement[r._id] || [];
                          const latestArtifacts = getLatestArtifacts(requirementArtifacts);
                          const selectedArtifact = requirementArtifacts.find(
                            artifact => artifact.artifact_id === selectedArtifactId,
                          ) || latestArtifacts[0];
                          const generatedTestCases = testCasesByRequirement[r._id] || [];
                          const executionRuns = executionRunsByRequirement[r._id] || [];
                          const executableTests = executableTestsByRequirement[r._id] || [];

                          return (
                            <div className="code-artifacts mt-3">
                              <div className="code-artifacts-header">
                                <h4>Generated Code</h4>
                                <div className="action-group">
                                  <button
                                    className="btn-primary"
                                    onClick={() => generateCode(r)}
                                    disabled={loading}
                                  >
                                    Generate Code
                                  </button>
                                  <button
                                    className="btn-success"
                                    onClick={() => generateTestCases(r)}
                                    disabled={loading || generatingTestCasesId === r._id}
                                  >
                                    {generatingTestCasesId === r._id ? 'Generating Test Cases...' : 'Generate Test Cases'}
                                  </button>
                                </div>
                              </div>

                              {generatedTestCases.length > 0 && (
                                <div className="test-cases-panel">
                                  <h4>AI Generated Test Cases</h4>
                                  <div className="test-cases-table-wrap">
                                    <table className="test-case-table">
                                      <thead>
                                        <tr>
                                          <th>Title</th>
                                          <th>Description</th>
                                          <th>Input</th>
                                          <th>Expected Output</th>
                                          <th>Priority</th>
                                          <th>Type</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {generatedTestCases.map(testCase => (
                                          <tr key={testCase.test_case_id}>
                                            <td>{testCase.title}</td>
                                            <td>{testCase.description}</td>
                                            <td>{testCase.input}</td>
                                            <td>{testCase.expected_output}</td>
                                            <td><span className="tag test-priority">{testCase.priority}</span></td>
                                            <td><span className="tag test-type">{testCase.type}</span></td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              )}

                              <div className="execution-panel mt-4">
                                <div className="code-artifacts-header">
                                  <h4>Executable JUnit Test</h4>
                                  <div className="action-group">
                                    <button
                                      className="btn-primary"
                                      onClick={() => generateExecutableTest(r)}
                                      disabled={loading || generatingExecutableTestId === r._id}
                                    >
                                      {generatingExecutableTestId === r._id ? 'Generating...' : 'Generate JUnit Test'}
                                    </button>
                                    <button
                                      className="btn-secondary"
                                      onClick={() => saveExecutableTest(r)}
                                      disabled={loading || savingExecutableTestId === r._id || !executableTestDraft.trim()}
                                    >
                                      {savingExecutableTestId === r._id ? 'Saving...' : 'Save New Version'}
                                    </button>
                                    <button
                                      className="btn-success"
                                      onClick={() => runTests(r)}
                                      disabled={loading || runningExecutionId === r._id || !selectedExecutableTestId}
                                    >
                                      {runningExecutionId === r._id ? 'Running Tests...' : 'Run Tests'}
                                    </button>
                                  </div>
                                </div>

                                {executableTests.length === 0 ? (
                                  <p className="code-empty">
                                    No executable JUnit test yet. Descriptive test cases are
                                    not executable code — generate a JUnit 5 test that
                                    implements them, then run it inside a secure container.
                                  </p>
                                ) : (
                                  <>
                                    <div className="code-file-list">
                                      <h5>Executable Test Versions</h5>
                                      {executableTests.map(test => (
                                        <button
                                          key={test.executable_test_id}
                                          className={`version-button ${selectedExecutableTestId === test.executable_test_id ? 'active' : ''}`}
                                          onClick={() => {
                                            setSelectedExecutableTestId(test.executable_test_id);
                                            setExecutableTestDraft(test.content);
                                          }}
                                        >
                                          {test.file_name} v{test.version}
                                          <span className="version-source">{test.source}</span>
                                        </button>
                                      ))}
                                    </div>
                                    <textarea
                                      value={executableTestDraft}
                                      onChange={event => setExecutableTestDraft(event.target.value)}
          className="exec-test-textarea"
          spellCheck={false}
                                    />
                                  </>
                                )}
                              </div>

                              <div className="execution-panel mt-4">
                                <div className="code-artifacts-header">
                                  <h4>Test Execution History</h4>
                                </div>

                                {executionRuns.length === 0 ? (
                                  <p className="code-empty">No execution records yet. Execution is disabled by default until a secure sandbox is configured.</p>
                                ) : (
                                  <div className="execution-list">
                                    {executionRuns.map(run => (
                                      <div key={run.execution_id} className="card mt-2">
                                        <div className="req-header">
                                          <h5>{run.execution_id}</h5>
                                          <span className="tag status">{run.status}</span>
                                        </div>
                                        <p>
                                          <strong>Artifact:</strong> {run.artifact.file_name} (v{run.artifact.version})
                                          {run.executable_test_class ? ` · Test: ${run.executable_test_class}` : ''}
                                        </p>
                                        {run.runner ? <p><strong>Runner:</strong> {run.runner}</p> : null}
                                        {run.duration_ms !== null && run.duration_ms !== undefined ? (
                                          <p><strong>Duration:</strong> {run.duration_ms} ms</p>
                                        ) : null}
                                        {run.counts ? (
                                          <p className="exec-counts">
                                            <strong>Results:</strong> {run.counts.passed} passed · {run.counts.failed} failed · {run.counts.skipped} skipped · {run.counts.error} errors (total {run.counts.total})
                                          </p>
                                        ) : null}
                                        {run.compile_result && run.compile_result.status !== 'PASSED' ? (
                                          <div className="compile-result failed">
                                            <strong>Compilation {run.compile_result.status}</strong>
                                            {run.compile_result.stderr ? <pre>{run.compile_result.stderr}</pre> : null}
                                          </div>
                                        ) : null}
                                        {run.error_message ? (
                                          <p className="exec-error">
                                            <strong>{run.status === 'ERROR' ? 'Runner / infrastructure error' : 'Message'}:</strong> {run.error_message}
                                          </p>
                                        ) : null}
                                        {run.source_snapshot && run.source_snapshot.length > 0 ? (
                                          <p className="code-empty">
                                            Source snapshot: {run.source_snapshot.map(f => `${f.file_name} v${f.version}`).join(', ')}
                                          </p>
                                        ) : null}
                                        {run.test_results.length === 0 ? (
                                          <p className="code-empty">No individual test results recorded.</p>
                                        ) : (
                                          <table className="test-case-table">
                                            <thead>
                                              <tr>
                                                <th>Test</th>
                                                <th>Method</th>
                                                <th>Status</th>
                                                <th>Expected</th>
                                                <th>Duration</th>
                                                <th>Details</th>
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {run.test_results.map(result => (
                                                <tr key={`${run.execution_id}-${result.test_id}`}>
                                                  <td>
                                                    {result.title}
                                                    {result.test_case_id ? (
                                                      <span className="coverage-id"> {result.test_case_id}</span>
                                                    ) : null}
                                                  </td>
                                                  <td>{result.method || '—'}</td>
                                                  <td>{result.status}</td>
                                                  <td>{result.expected_output || '—'}</td>
                                                  <td>{result.duration_ms !== null && result.duration_ms !== undefined ? `${result.duration_ms} ms` : '—'}</td>
                                                  <td>
                                                    {result.error_details ? (
                                                      <span title={result.error_details}>
                                                        {result.error_details.length > 60
                                                          ? `${result.error_details.slice(0, 60)}…`
                                                          : result.error_details}
                                                      </span>
                                                    ) : '—'}
                                                  </td>
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>


                              {latestArtifacts.length === 0 ? (
                                <p className="code-empty">No generated files yet.</p>
                              ) : (
                                <div className="code-workspace">
                                  <div className="code-file-list">
                                    <h5>Files</h5>
                                    {latestArtifacts.map(artifact => (
                                      <button
                                        key={artifact.file_name}
                                        className={`code-file-button ${selectedArtifact?.file_name === artifact.file_name ? 'active' : ''}`}
                                        onClick={() => selectArtifact(artifact)}
                                      >
                                        {artifact.file_name}
                                        <span>v{artifact.version}</span>
                                      </button>
                                    ))}
                                    <h5 className="version-heading">Versions</h5>
                                    {requirementArtifacts.map(artifact => (
                                      <button
                                        key={artifact.artifact_id}
                                        className={`version-button ${selectedArtifact?.artifact_id === artifact.artifact_id ? 'active' : ''}`}
                                        onClick={() => selectArtifact(artifact)}
                                      >
                                        {artifact.file_name} v{artifact.version}
                                        <span className="version-source">{artifact.source}</span>
                                      </button>
                                    ))}
                                  </div>
                                  {selectedArtifact && (
                                    <div className="code-editor">
                                      <div className="code-editor-header">
                                        <strong>{selectedArtifact.file_name}</strong>
                                        <span>
                                          v{selectedArtifact.version} · {selectedArtifact.source} · ID {selectedArtifact.artifact_id}
                                        </span>
                                      </div>
                                      <textarea
                                        value={selectedArtifactId === selectedArtifact.artifact_id ? draftArtifactContent : selectedArtifact.content}
                                        onChange={event => {
                                          setSelectedArtifactId(selectedArtifact.artifact_id);
                                          setDraftArtifactContent(event.target.value);
                                        }}
                                        spellCheck={false}
                                      />
                                      <button
                                        className="btn-success mt-3"
                                        onClick={() => saveArtifact(selectedArtifact)}
                                        disabled={savingArtifact}
                                      >
                                        Save New Version
                                      </button>
                                      <button
                                        className="btn-primary mt-3 compile-button"
                                        onClick={() => compileArtifact(selectedArtifact)}
                                        disabled={compilingArtifactId === selectedArtifact.artifact_id}
                                      >
                                        {compilingArtifactId === selectedArtifact.artifact_id ? 'Compiling...' : 'Compile'}
                                      </button>
                                      {compileResults[selectedArtifact.artifact_id] && (
                                        <div className={`compile-result ${compileResults[selectedArtifact.artifact_id].status.toLowerCase()}`}>
                                          <strong>BUILD {compileResults[selectedArtifact.artifact_id].status}</strong>
                                          <span>Exit Code: {compileResults[selectedArtifact.artifact_id].exit_code ?? 'N/A'}</span>
                                          <span>Compilation Time: {compileResults[selectedArtifact.artifact_id].duration_ms} ms</span>
                                          {compileResults[selectedArtifact.artifact_id].stdout && (
                                            <pre>{compileResults[selectedArtifact.artifact_id].stdout}</pre>
                                          )}
                                          {compileResults[selectedArtifact.artifact_id].stderr && (
                                            <pre>{compileResults[selectedArtifact.artifact_id].stderr}</pre>
                                          )}
                                        </div>
                                      )}
                                      <button
                                        className="btn-primary mt-3"
                                        onClick={() => analyzeArtifact(selectedArtifact)}
                                        disabled={analyzingArtifactId === selectedArtifact.artifact_id}
                                      >
                                        {analyzingArtifactId === selectedArtifact.artifact_id ? 'Analyzing...' : 'Run Static Analysis'}
                                      </button>
                                      {analysisResults[selectedArtifact.artifact_id] && (
                                        <div className="analysis-tools-result">
                                          <h5>Static Analysis</h5>
                                          <span>Overall status: {analysisResults[selectedArtifact.artifact_id].status}</span>
                                          <span className="analysis-scope">
                                            Analyzed {selectedArtifact.file_name} v{analysisResults[selectedArtifact.artifact_id].version ?? '?'}
                                            {' · '}{new Date(analysisResults[selectedArtifact.artifact_id].created_at).toLocaleString()}
                                          </span>
                                          {analysisResults[selectedArtifact.artifact_id].analyzed_files?.length > 0 && (
                                            <span className="analysis-scope">
                                              Snapshot: {analysisResults[selectedArtifact.artifact_id].analyzed_files
                                                .map(f => `${f.file_name} v${f.version}`)
                                                .join(', ')}
                                            </span>
                                          )}
                                          {([
                                            ['Checkstyle', analysisResults[selectedArtifact.artifact_id].checkstyle],
                                            ['SpotBugs', analysisResults[selectedArtifact.artifact_id].spotbugs],
                                            ['Security', analysisResults[selectedArtifact.artifact_id].security],
                                          ] as [string, AnalysisToolResult][]).map(([label, toolResult]) => (
                                            <div className="analysis-tool-group" key={label}>
                                              <div className="analysis-tool-heading">
                                                <strong>{label}</strong>
                                                <span>{toolResult.status} · {toolResult.findings.length} findings</span>
                                              </div>
                                              {toolResult.findings.map((finding, index) => (
                                                <div className="analysis-finding" key={`${finding.tool}-${finding.file}-${finding.line}-${index}`}>
                                                  <strong>{finding.severity}</strong>
                                                  <span>{finding.file}:{finding.line ?? 'n/a'}{finding.column ? `:${finding.column}` : ''}</span>
                                                  <span>{finding.rule || finding.tool}</span>
                                                  <p>{finding.message}</p>
                                                </div>
                                              ))}
                                            </div>
                                          ))}
                                        </div>
                                      )}

                                      {/* AI Code Improvement Section */}
                                      {analysisResults[selectedArtifact.artifact_id] && (
                                        <div className="improvement-section mt-4">
                                          <div className="improvement-header">
                                            <h4>AI Code Improvement</h4>
                                            <button
                                              className="btn-primary"
                                              onClick={() => generateImprovement(selectedArtifact)}
                                              disabled={improvementLoading}
                                            >
                                              {improvementLoading ? 'Generating...' : 'Generate Improved Code'}
                                            </button>
                                          </div>

                                          {improvementError && (
                                            <div className="alert error mt-3">{improvementError}</div>
                                          )}

                                          {improvementNotice && (
                                            <div className="alert info mt-3">{improvementNotice}</div>
                                          )}

                                          {proposalHistory.length > 1 && (
                                            <div className="proposal-history-selector mt-3">
                                              <span className="history-selector-label">Review History ({proposalHistory.length}):</span>
                                              <div className="history-buttons">
                                                {proposalHistory.map((p, idx) => (
                                                  <button
                                                    key={p.proposal_id}
                                                    className={`btn-history-pill ${improvementProposal?.proposal_id === p.proposal_id ? 'active' : ''}`}
                                                    onClick={() => selectProposal(p)}
                                                  >
                                                    #{proposalHistory.length - idx} <span className={`tag-micro ${p.status.toLowerCase()}`}>{p.status}</span>
                                                  </button>
                                                ))}
                                              </div>
                                            </div>
                                          )}

                                          {improvementProposal && (
                                            <div className="improvement-proposal mt-3">
                                              {/* HITL Review Status Banner */}
                                              {improvementProposal.status === 'PENDING' && (
                                                <div className="hitl-banner pending">
                                                  <span className="hitl-banner-badge">DECISION PENDING</span>
                                                  <div>
                                                    <strong>Human-in-the-Loop Review Required</strong>
                                                    <p>Inspect findings, assessments, and proposed code diff below before approving or rejecting.</p>
                                                  </div>
                                                </div>
                                              )}

                                              {improvementProposal.status === 'ACCEPTED' && (
                                                <div className="hitl-banner accepted">
                                                  <span className="hitl-banner-badge">ACCEPTED</span>
                                                  <div>
                                                    <strong>Proposal Approved &amp; Applied</strong>
                                                    <p>
                                                      Approved by <strong>{improvementProposal.reviewer || 'Local Developer'}</strong>
                                                      {improvementProposal.decision_timestamp || improvementProposal.accepted_at ? ` on ${new Date(improvementProposal.decision_timestamp || improvementProposal.accepted_at!).toLocaleString()}` : ''}.
                                                      Created artifact version <strong>v{improvementProposal.accepted_version}</strong>.
                                                    </p>
                                                  </div>
                                                </div>
                                              )}

                                              {improvementProposal.status === 'REJECTED' && (
                                                <div className="hitl-banner rejected">
                                                  <span className="hitl-banner-badge">REJECTED</span>
                                                  <div>
                                                    <strong>Proposal Rejected</strong>
                                                    <p>
                                                      Rejected by <strong>{improvementProposal.reviewer || 'Local Developer'}</strong>
                                                      {improvementProposal.decision_timestamp || improvementProposal.rejected_at ? ` on ${new Date(improvementProposal.decision_timestamp || improvementProposal.rejected_at!).toLocaleString()}` : ''}.
                                                      Original code was preserved without modification.
                                                    </p>
                                                  </div>
                                                </div>
                                              )}

                                              {improvementProposal.status === 'NO_CHANGE' && (
                                                <div className="hitl-banner no-change">
                                                  <span className="hitl-banner-badge">NO CHANGE</span>
                                                  <div>
                                                    <strong>Review Completed — No Modification Recommended</strong>
                                                    <p>The AI reviewed findings and determined no safe code modifications are required. This record is read-only.</p>
                                                  </div>
                                                </div>
                                              )}

                                              <div className="improvement-proposal-header mt-2">
                                                <div>
                                                  <h5>
                                                    Improvement Proposal for{' '}
                                                    <code className="proposal-file">{improvementProposal.file_name}</code>
                                                  </h5>
                                                  <span className="proposal-target-version">
                                                    Target file: {improvementProposal.file_name} (base v{improvementProposal.source_version ?? selectedArtifact?.version ?? 1})
                                                  </span>
                                                </div>
                                                <span className={`tag status ${improvementProposal.status.toLowerCase()}`}>
                                                  {improvementProposal.status}
                                                </span>
                                              </div>

                                              {improvementProposal.review_comment && (
                                                <div className="reviewer-comment-box mt-2">
                                                  <h6>Reviewer Comment / Rationale</h6>
                                                  <p>{improvementProposal.review_comment}</p>
                                                  <small>Decision recorded: {improvementProposal.reviewer || 'Local Developer'} · {new Date(improvementProposal.decision_timestamp || improvementProposal.updated_at).toLocaleString()}</small>
                                                </div>
                                              )}
                                              {improvementProposal.file_name !== selectedArtifact?.file_name && (
                                                <p className="finding-note">
                                                  The findings were in{' '}
                                                  <strong>{improvementProposal.file_name}</strong>, not the selected{' '}
                                                  {selectedArtifact?.file_name} — accept creates a new version of{' '}
                                                  {improvementProposal.file_name}.
                                                </p>
                                              )}

                                              <div className="improvement-explanation">
                                                <h6>AI Explanation</h6>
                                                <p>{improvementProposal.explanation}</p>
                                              </div>

                                              {improvementProposal.finding_assessments?.length > 0 && (
                                                <div className="improvement-findings assessments">
                                                  <h6>Per-Finding Assessments ({improvementProposal.finding_assessments.length})</h6>
                                                  <p className="finding-honest-note">
                                                    Verdicts below reflect the AI review. Findings are genuinely resolved only after re-analysis on accepted source confirms it. Non-actionable and needs-context findings are preserved and never suppressed.
                                                  </p>
                                                  <ul>
                                                    {improvementProposal.finding_assessments.map((a, idx) => (
                                                      <li key={idx} className="assessment-item">
                                                        <div
                                                          className="assessment-item-header"
                                                          onClick={() => setExpandedFindings(curr => ({
                                                            ...curr,
                                                            [`${improvementProposal.proposal_id}-${a.finding_id}`]: !curr[`${improvementProposal.proposal_id}-${a.finding_id}`],
                                                          }))}
                                                        >
                                                          <span className={`assessment-tag ${a.classification.toLowerCase()}`}>
                                                            {a.finding_id} · {a.classification}
                                                          </span>
                                                          <span className="assessment-toggle-hint">
                                                            {expandedFindings[`${improvementProposal.proposal_id}-${a.finding_id}`] ? '▲ Hide reasoning' : '▼ View reasoning'}
                                                          </span>
                                                        </div>
                                                        {expandedFindings[`${improvementProposal.proposal_id}-${a.finding_id}`] && a.reasoning && (
                                                          <div className="assessment-detail-body">
                                                            <strong>AI Assessment Rationale:</strong> {a.reasoning}
                                                          </div>
                                                        )}
                                                      </li>
                                                    ))}
                                                  </ul>
                                                </div>
                                              )}

                                              {improvementProposal.formatting_notes && improvementProposal.formatting_notes.length > 0 && (
                                                <div className="improvement-findings formatting-notes">
                                                  <h6>Formatting Guard</h6>
                                                  <ul>
                                                    {improvementProposal.formatting_notes.map((note, idx) => (
                                                      <li key={idx}>{note}</li>
                                                    ))}
                                                  </ul>
                                                  <p className="finding-note">
                                                    These whitespace changes were unrelated to any finding and were reverted to
                                                    your original code before saving the proposal.
                                                  </p>
                                                </div>
                                              )}

                                              {improvementProposal.findings_addressed.length > 0 && (
                                                <div className="improvement-findings">
                                                  <h6>Findings Addressed</h6>
                                                  <ul>
                                                    {improvementProposal.findings_addressed.map((finding, idx) => (
                                                      <li key={idx}>
                                                        <strong>{finding.tool}</strong> - {finding.rule || finding.file}:{finding.line ?? 'n/a'} - {finding.message}
                                                      </li>
                                                    ))}
                                                  </ul>
                                                </div>
                                              )}

                                              {improvementProposal.non_actionable_findings.length > 0 && (
                                                <div className="improvement-findings non-actionable">
                                                  <h6>Findings Not Fixed</h6>
                                                  <ul>
                                                    {improvementProposal.non_actionable_findings.map((finding, idx) => (
                                                      <li key={idx}>
                                                        <strong>{finding.tool}</strong> - {finding.rule || finding.file}:{finding.line ?? 'n/a'} - {finding.message}
                                                      </li>
                                                    ))}
                                                  </ul>
                                                  <p className="finding-note">
                                                    These are preserved and re-checked on the new version — not deleted or marked resolved.
                                                  </p>
                                                </div>
                                              )}

                                              {improvementDiff && (
                                                <div className="improvement-diff">
                                                  <h6>Code Diff</h6>
                                                  <pre className="diff-view">{improvementDiff}</pre>
                                                </div>
                                              )}

                                              {/* Reviewer Action Controls (for PENDING proposals) */}
                                              {improvementProposal.status === 'PENDING' && (
                                                <div className="hitl-decision-panel mt-3">
                                                  <h6>Human Review Decision</h6>
                                                  <div className="form-group mb-3">
                                                    <label htmlFor="review-comment-input">Reviewer Feedback / Decision Notes (optional):</label>
                                                    <textarea
                                                      id="review-comment-input"
                                                      className="review-comment-input"
                                                      placeholder="Enter optional comments or rationale for your approval/rejection..."
                                                      value={reviewComment}
                                                      onChange={e => setReviewComment(e.target.value)}
                                                      rows={2}
                                                    />
                                                  </div>

                                                  {confirmAction === null ? (
                                                    <div className="improvement-actions">
                                                      <button
                                                        className="btn-success"
                                                        onClick={() => setConfirmAction('APPROVE')}
                                                        disabled={acceptingProposal || rejectingProposal}
                                                      >
                                                        Approve Changes...
                                                      </button>
                                                      <button
                                                        className="btn-secondary"
                                                        onClick={() => setConfirmAction('REJECT')}
                                                        disabled={acceptingProposal || rejectingProposal}
                                                      >
                                                        Reject Proposal...
                                                      </button>
                                                    </div>
                                                  ) : confirmAction === 'APPROVE' ? (
                                                    <div className="confirm-decision-box approve-box">
                                                      <p>
                                                        <strong>Confirm Approval:</strong> Approving will create a new artifact version for <code>{improvementProposal.file_name}</code>, run Java structural validation and formatting guard, compile the new version, and run static analysis verification. Previous versions remain preserved.
                                                      </p>
                                                      <div className="confirm-buttons">
                                                        <button
                                                          className="btn-success"
                                                          onClick={() => acceptProposal(improvementProposal)}
                                                          disabled={acceptingProposal}
                                                        >
                                                          {acceptingProposal ? 'Applying & Verifying...' : 'Confirm Approval & Apply'}
                                                        </button>
                                                        <button
                                                          className="btn-outline"
                                                          onClick={() => setConfirmAction(null)}
                                                          disabled={acceptingProposal}
                                                        >
                                                          Cancel
                                                        </button>
                                                      </div>
                                                    </div>
                                                  ) : (
                                                    <div className="confirm-decision-box reject-box">
                                                      <p>
                                                        <strong>Confirm Rejection:</strong> Rejecting will mark this proposal as REJECTED. No files will be modified and no new versions will be created.
                                                      </p>
                                                      <div className="confirm-buttons">
                                                        <button
                                                          className="btn-danger"
                                                          onClick={() => rejectProposal(improvementProposal)}
                                                          disabled={rejectingProposal}
                                                        >
                                                          {rejectingProposal ? 'Rejecting...' : 'Confirm Rejection'}
                                                        </button>
                                                        <button
                                                          className="btn-outline"
                                                          onClick={() => setConfirmAction(null)}
                                                          disabled={rejectingProposal}
                                                        >
                                                          Cancel
                                                        </button>
                                                      </div>
                                                    </div>
                                                  )}
                                                </div>
                                              )}

                                              {improvementProposal.status === 'ACCEPTED' && improvementProposal.compile_result && (
                                                <div className="improvement-verification">
                                                  <h6>Verification Results</h6>
                                                  <div className={`compile-result ${improvementProposal.compile_result.status.toLowerCase()}`}>
                                                    <strong>BUILD {improvementProposal.compile_result.status}</strong>
                                                    <span>Exit Code: {improvementProposal.compile_result.exit_code ?? 'N/A'}</span>
                                                    <span>Compilation Time: {improvementProposal.compile_result.duration_ms} ms</span>
                                                  </div>
                                                  {improvementProposal.accepted_artifact_id && (
                                                    <p className="mt-2">
                                                      <strong>New Version:</strong> Artifact ID: {improvementProposal.accepted_artifact_id}, Version: {improvementProposal.accepted_version}
                                                    </p>
                                                  )}
                                                </div>
                                              )}

                                              {improvementComparison && (
                                                <div className="improvement-comparison">
                                                  <h6>Before &amp; After Comparison</h6>
                                                  <div className="comparison-summary">
                                                    <div className="comparison-metric">
                                                      <span>Findings Before</span>
                                                      <strong>{improvementComparison.total_before}</strong>
                                                    </div>
                                                    <div className="comparison-metric">
                                                      <span>Findings After</span>
                                                      <strong>{improvementComparison.total_after}</strong>
                                                    </div>
                                                    <div className="comparison-metric">
                                                      <span>Resolved</span>
                                                      <strong>{improvementComparison.findings_resolved.length}</strong>
                                                    </div>
                                                    <div className="comparison-metric">
                                                      <span>Remaining</span>
                                                      <strong>{improvementComparison.findings_remaining.length}</strong>
                                                    </div>
                                                    <div className="comparison-metric">
                                                      <span>New</span>
                                                      <strong>{improvementComparison.findings_new.length}</strong>
                                                    </div>
                                                  </div>

                                                  {improvementComparison.findings_resolved.length > 0 && (
                                                    <div className="comparison-section">
                                                      <h6>Resolved Findings</h6>
                                                      <ul>
                                                        {improvementComparison.findings_resolved.map((finding, idx) => (
                                                          <li key={idx} className="comparison-resolved">
                                                            <strong>{finding.tool}</strong> - {finding.rule || finding.file} - {finding.message}
                                                          </li>
                                                        ))}
                                                      </ul>
                                                    </div>
                                                  )}

                                                  {improvementComparison.findings_remaining.length > 0 && (
                                                    <div className="comparison-section">
                                                      <h6>Remaining Findings</h6>
                                                      <ul>
                                                        {improvementComparison.findings_remaining.map((finding, idx) => (
                                                          <li key={idx} className="comparison-remaining">
                                                            <strong>{finding.tool}</strong> - {finding.rule || finding.file} - {finding.message}
                                                          </li>
                                                        ))}
                                                      </ul>
                                                    </div>
                                                  )}

                                                  {improvementComparison.findings_new.length > 0 && (
                                                    <div className="comparison-section">
                                                      <h6>New Findings</h6>
                                                      <ul>
                                                        {improvementComparison.findings_new.map((finding, idx) => (
                                                          <li key={idx} className="comparison-new">
                                                            <strong>{finding.tool}</strong> - {finding.rule || finding.file} - {finding.message}
                                                          </li>
                                                        ))}
                                                      </ul>
                                                    </div>
                                                  )}
                                                </div>
                                              )}
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </li>
                    ))}
                  </ul>
                )}


                {/* Git/Repository Section */}
                <div className="card mt-4">
                  <div className="coverage-report-header">
                    <div>
                      <h2>Git Repository</h2>
                      <p>Manage the source code repository for your project.</p>
                    </div>
                  </div>

                  {/* Initialize/Connect Controls */}
                  {selectedProject && (
                    <div className="git-controls">
                      {git.state.isInitialized || (git.state.status && git.state.status.is_repo) ? (
                        <div className="git-initialized-badge">
                          <span className="badge badge-success">✓ Repository Initialized</span>
                        </div>
                      ) : (
                        <button
                          className="btn-primary mt-2"
                          onClick={() => git.fetchInit()}
                          disabled={git.state.loading}
                        >
                          {git.state.loading ? 'Initializing Repository...' : 'Initialize Repository'}
                        </button>
                      )}
                    </div>
                  )}

                  {selectedProject && git.state.isConnected && (
                    <p>Connected to Git repository</p>
                  )}

                  {/* Repository Status */}
                  {selectedProject && git.state.status && git.state.status.is_repo ? (
                    <div className="git-status-panel">
                      <div className="git-header">
                        <h3>Repository Status</h3>
                        <span className="git-branch">Branch: {git.state.status.branch}</span>
                      </div>

                      <div className="git-status-info">
                        <p>{git.state.status.is_clean ? 'Working tree is clean' : 'Working tree is dirty'}</p>

                        {git.state.status.modified_files.length > 0 && (
                          <div className="git-panel-section">
                            <h5>Modified Files</h5>
                            <ul>
                              {git.state.status.modified_files.map((f: string) => (
                                <li key={f}>{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {git.state.status.added_files.length > 0 && (
                          <div className="git-panel-section">
                            <h5>Added Files</h5>
                            <ul>
                              {git.state.status.added_files.map((f: string) => (
                                <li key={f}>{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {git.state.status.deleted_files.length > 0 && (
                          <div className="git-panel-section">
                            <h5>Deleted Files</h5>
                            <ul>
                              {git.state.status.deleted_files.map((f: string) => (
                                <li key={f}>{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {git.state.status.untracked_files.length > 0 && (
                          <div className="git-panel-section">
                            <h5>Untracked Files</h5>
                            <ul>
                              {git.state.status.untracked_files.map((f: string) => (
                                <li key={f}>{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>

                      <div className="git-latest-commit">
                        {git.state.status.latest_commit && git.state.status.latest_commit.message ? (
                          <div>
                            <strong>Latest Commit:</strong> {git.state.status.latest_commit.message}
                            <br />
                            <small>Author: {git.state.status.latest_commit.author || 'Unknown'} & {git.state.status.latest_commit.date || ''}</small>
                          </div>
                        ) : (
                          <p>No commits yet.</p>
                        )}
                      </div>
                    </div>
                  ) : selectedProject && (
                    <div className="git-status-empty">
                      <p>Initialize a Git repository to view repository status.</p>
                    </div>
                  )}

                  {/* Stage/Unstaged Files */}
                  {selectedProject && git.state.status && git.state.status.is_repo && (
                    <div className="git-changes">
                      <h5>Changes</h5>
                      <div className="git-changes-grid">
                        <div>
                          <h6>Staged</h6>
                          <p>{git.state.status.staged_diff_stat || (git.state.status.staged_diff ? 'Changes staged' : 'No staged changes')}</p>
                          <button
                            className="btn-secondary small"
                            onClick={() => git.fetchStage([])}
                            disabled={git.state.loading || (!git.state.status.modified_files.length && !git.state.status.added_files.length && !git.state.status.deleted_files.length && !git.state.status.untracked_files.length)}
                          >
                            Stage All
                          </button>
                        </div>
                        <div>
                          <h6>Unstaged</h6>
                          <p>{git.state.status.unstaged_diff ? (git.state.status.unstaged_diff.substring(0, 100) + (git.state.status.unstaged_diff.length > 100 ? '...' : '')) : (git.state.status.untracked_files.length > 0 ? `${git.state.status.untracked_files.length} untracked file(s)` : 'No unstaged changes')}</p>
                          <button
                            className="btn-secondary small"
                            onClick={() => git.fetchUnstage([])}
                            disabled={git.state.loading || (!git.state.status.staged_diff && !git.state.status.staged_diff_stat)}
                          >
                            Unstage All
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Commit Section - only rendered after repository is initialized */}
                  {selectedProject && git.state.status && git.state.status.is_repo && (
                    <div className="git-commit">
                      <h5>Create Commit</h5>
                      <div className="git-commit-input">
                        <input
                          type="text"
                          value={git.state.commitMessage}
                          onChange={e => git.setState(prev => ({ ...prev, commitMessage: e.target.value }))}
                          placeholder="Enter commit message"
                          disabled={git.state.loading}
                        />
                        <button
                          className="btn-primary"
                          onClick={() => git.fetchCommit()}
                          disabled={!git.state.commitMessage.trim() || git.state.loading}
                        >
                          {git.state.loading ? 'Creating...' : 'Commit'}
                        </button>
                      </div>
                      {git.state.showCommitConfirmation && (
                        <div className="git-commit-confirm">
                          <p>Create commit with message: "{git.state.commitMessage}"?</p>
                          <button className="btn-primary" onClick={() => git.confirmCommit()} disabled={git.state.loading}>Commit</button>
                          <button className="btn-secondary" onClick={() => git.setState(prev => ({ ...prev, showCommitConfirmation: false }))} disabled={git.state.loading}>Cancel</button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Commit History */}
                  {selectedProject && git.state.status && git.state.status.is_repo && git.state.commits.length > 0 && (
                    <div className="git-history">
                      <h5>Commit History</h5>
                      <ul>
                        {git.state.commits.map((commit, i) => (
                          <li key={i} onClick={() => git.fetchCommitDetails(commit.hash)}>
                            <strong>{commit.hash.substring(0, 7)}</strong> {commit.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Diff View */}
                  {git.state.showDiff && git.state.diffContent && (
                    <div className="git-diff-view">
                      <h5>Diff</h5>
                      <div className="diff-scroll">
                        <pre>{git.state.diffContent}</pre>
                      </div>
                      <button className="btn-secondary" onClick={() => git.setState(prev => ({ ...prev, showDiff: false }))}>Close</button>
                    </div>
                  )}
                </div>

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