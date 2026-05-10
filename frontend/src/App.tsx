import { Routes, Route } from 'react-router-dom'
import HomePage from './pages/HomePage'
import AnalysisPage from './pages/AnalysisPage'
import ResultPage from './pages/ResultPage'
import HistoryPage from './pages/HistoryPage'
import OntologyPage from './pages/OntologyPage'
import PtOntologyPage from './pages/PtOntologyPage'
import Layout from './components/common/Layout'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/result/:id" element={<ResultPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/ontology" element={<OntologyPage />} />
        <Route path="/ptontology" element={<PtOntologyPage />} />
      </Routes>
    </Layout>
  )
}

export default App
