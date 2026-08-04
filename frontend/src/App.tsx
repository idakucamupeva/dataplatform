import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { useAuth } from '@/lib/auth'
import { LoginPage } from '@/pages/Login'
import { OverviewPage } from '@/pages/Overview'
import { DataProductsPage } from '@/pages/DataProducts'
import { CreateDataProductPage } from '@/pages/CreateDataProduct'
import { DataProductDetailPage } from '@/pages/DataProductDetail'
import { MarketplacePage } from '@/pages/Marketplace'
import { MarketplaceDetailPage } from '@/pages/MarketplaceDetail'
import { AccessPage } from '@/pages/Access'
import { GovernancePage } from '@/pages/Governance'
import { DomainsPage } from '@/pages/Domains'
import { LineagePage } from '@/pages/Lineage'

export function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="login-page">
        <div className="muted">Loading the platform…</div>
      </div>
    )
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/products" element={<DataProductsPage />} />
        <Route path="/products/:id" element={<DataProductDetailPage />} />
        <Route path="/create" element={<CreateDataProductPage />} />
        <Route path="/marketplace" element={<MarketplacePage />} />
        <Route path="/marketplace/:id" element={<MarketplaceDetailPage />} />
        <Route path="/access" element={<AccessPage />} />
        <Route path="/governance" element={<GovernancePage />} />
        <Route path="/domains" element={<DomainsPage />} />
        <Route path="/lineage" element={<LineagePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
