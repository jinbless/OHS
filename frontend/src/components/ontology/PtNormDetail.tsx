import React from 'react';
import type { ArticleNorms } from '../../api/ontologyApi';

interface PtNormDetailProps {
  data: ArticleNorms;
}

const EFFECT_COLORS: Record<string, string> = {
  OBLIGATION: 'bg-blue-100 text-blue-800',
  PROHIBITION: 'bg-red-100 text-red-800',
  PERMISSION: 'bg-green-100 text-green-800',
  EXCEPTION: 'bg-yellow-100 text-yellow-800',
};

const EFFECT_LABELS: Record<string, string> = {
  OBLIGATION: 'Obrigação',
  PROHIBITION: 'Proibição',
  PERMISSION: 'Permissão',
  EXCEPTION: 'Exceção',
};

const CATEGORY_LABELS: Record<string, string> = {
  safety: 'Segurança',
  equipment: 'Equipamento',
  procedure: 'Procedimento',
  management: 'Gestão',
};

const RELATION_LABELS: Record<string, string> = {
  IMPLEMENTS: 'Implementação',
  SPECIFIES_METHOD: 'Método',
  SPECIFIES_CRITERIA: 'Critério',
  SUPPLEMENTS: 'Suplemento',
  CROSS_REFERENCES: 'Referência',
};

const PtNormDetail: React.FC<PtNormDetailProps> = ({ data }) => {
  return (
    <div className="space-y-4">
      {/* Cabeçalho */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-lg font-bold text-blue-700">{data.article_number}</span>
          {data.article_title && (
            <span className="text-gray-600">{data.article_title}</span>
          )}
        </div>
        <div className="text-sm text-gray-500">
          {data.total_norms} proposições normativas / {data.linked_guides.length} guias conectados
        </div>
      </div>

      {/* Lista de proposições normativas */}
      <div className="bg-white rounded-xl shadow-sm border overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 border-b">
          <h3 className="font-semibold text-sm text-gray-700">Proposições Normativas (NormStatement)</h3>
        </div>
        <div className="divide-y">
          {data.norms.map((norm) => (
            <div key={norm.id} className="px-4 py-3 hover:bg-gray-50">
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    EFFECT_COLORS[norm.legal_effect] || 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {EFFECT_LABELS[norm.legal_effect] || norm.legal_effect}
                </span>
                {norm.paragraph && (
                  <span className="text-xs text-gray-400">{norm.paragraph}</span>
                )}
                {norm.norm_category && (
                  <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
                    {CATEGORY_LABELS[norm.norm_category] || norm.norm_category}
                  </span>
                )}
              </div>

              {/* Informações estruturadas */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs mb-2">
                {norm.subject_role && (
                  <div>
                    <span className="text-gray-400">Sujeito: </span>
                    <span className="font-medium text-gray-700">{norm.subject_role}</span>
                  </div>
                )}
                {norm.action && (
                  <div>
                    <span className="text-gray-400">Ação: </span>
                    <span className="font-medium text-gray-700">{norm.action}</span>
                  </div>
                )}
                {norm.object && (
                  <div>
                    <span className="text-gray-400">Objeto: </span>
                    <span className="font-medium text-gray-700">{norm.object}</span>
                  </div>
                )}
              </div>

              {norm.condition_text && (
                <div className="text-xs text-gray-500 mb-1">
                  <span className="text-gray-400">Condição: </span>{norm.condition_text}
                </div>
              )}

              <div className="text-xs text-gray-400 line-clamp-2 mt-1">
                {norm.full_text}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Guias conectados */}
      {data.linked_guides.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 border-b">
            <h3 className="font-semibold text-sm text-gray-700">KOSHA GUIDE Conectados</h3>
          </div>
          <div className="divide-y">
            {data.linked_guides.map((guide, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <div className="font-medium text-sm text-orange-700">{guide.guide_code}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{guide.title}</div>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
                    {RELATION_LABELS[guide.relation_type] || guide.relation_type}
                  </span>
                  <span className="text-gray-400">{(guide.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default PtNormDetail;
