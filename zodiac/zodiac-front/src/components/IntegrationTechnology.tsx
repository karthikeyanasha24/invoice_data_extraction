import {
  ArrowDown, Blocks, Building2, CheckCheck, FileText, Globe2,
  Layers3, Network, ShieldCheck,
} from 'lucide-react';
import styles from './IntegrationTechnology.module.css';

const patentTitle = 'E-ORDER AND E-INVOICE INTEGRATION UTILIZING SAP STANDARDS AND MIDDLEWARE';
const solutions = ['SAP EDI', 'SAP eInvoicing', 'Peppol', 'Global SAP Templates', 'CFDI / UBL / KSeF', 'Integration & Automation'];
const architecture = [
  'SAP ERP / S/4HANA', 'SAP-standard business data', 'Integration / Processing Layer',
  'Validation & Business Rules', 'Automated Error Resolution', 'E-Order / E-Invoice Processing',
  'Government / Peppol / Trading Partner', 'Monitoring & Analytics',
];
const capabilities = [
  { icon: Network, title: 'SAP-standard Integration', description: 'Integration with SAP-standard business processes and data structures.' },
  { icon: FileText, title: 'E-Order & E-Invoice Processing', description: 'Processing of electronic transaction documents originating from SAP business processes.' },
  { icon: CheckCheck, title: 'Validation', description: 'Validation of transactional data against configurable rules and requirements.' },
  { icon: ShieldCheck, title: 'Automated Exception Handling', description: 'Identification and automated handling of defined transaction errors and exceptions.' },
  { icon: Globe2, title: 'Multi-format / Multi-country', description: 'Support for international electronic-document and regulatory environments.' },
  { icon: Blocks, title: 'Monitoring & Analytics', description: 'Central visibility into transactions, processing status, errors and operational performance.' },
];
const milestones = [
  ['2010', 'Foundation', 'SAP integration and cockpit development begins, supported by development records and SAP partnership/namespace arrangements.'],
  ['2018', 'Enterprise Sales Cockpit', 'Technology implemented in an enterprise Sales-side cockpit environment.'],
  ['', 'Subsequent Enterprise Implementations', 'Deployment across SAP/EDI environments including Swiss Krono, Nolte GmbH and HR Path France.'],
  ['', 'eInvoicing Evolution', 'Application of the technology to electronic invoicing and international formats including CFDI and UBL.'],
  ['2024', 'U.S. Patent Application', 'U.S. patent application 18/673,332 filed.'],
  ['2026', 'USPTO Allowance', 'Claims allowed by the USPTO; issue fee paid and patent proceeding toward issuance.'],
];
const benefits = [
  ['For Global SAP Enterprises', 'Global Template', 'Extend a common SAP architecture across multiple countries and legal entities.'],
  ['For IT Teams', 'Centralised Control', 'Monitor electronic transactions and exceptions through a controlled integration architecture.'],
  ['For Finance & Compliance', 'Regulatory Adaptability', 'Support changing country-specific electronic invoicing and reporting requirements without redesigning the global SAP core.'],
  ['For SAP Partners', 'Integration Technology', 'A technology foundation that can complement SAP, EDI and eInvoicing ecosystems.'],
];
const partners = [
  { icon: Network, title: 'SAP technology and implementation partners' },
  { icon: FileText, title: 'EDI and eInvoicing providers' },
  { icon: Globe2, title: 'Global SAP solution providers' },
  { icon: Building2, title: 'Enterprise organisations operating global SAP templates' },
  { icon: Layers3, title: 'Technology companies seeking integration capabilities' },
];
const licensingModels = ['Enterprise Licensing', 'Global Template Licensing', 'OEM Arrangements', 'Strategic Technology Partnerships'];
const sections = [['home', 'Home'], ['solutions', 'Solutions'], ['technology', 'Technology'], ['patent', 'Patent & IP'], ['case-studies', 'Case Studies']];

function ArchitectureVisual() {
  return (
    <div className={styles.visual} aria-label="Architecture overview: SAP business data connects through integration and validation to electronic transactions and monitoring">
      <div className={styles.visualLabel}><span>Integration architecture</span><Network aria-hidden="true" /></div>
      <div className={styles.visualNode}>SAP ERP / S/4HANA<small>SAP-standard business data</small></div>
      <div className={styles.visualConnector}><ArrowDown aria-hidden="true" /></div>
      <div className={styles.visualNode + ' ' + styles.visualNodeAccent}>
        Integration / Processing Layer
        <div className={styles.visualTags}><span>Validation</span><span>Exception handling</span><span>Document creation</span></div>
      </div>
      <div className={styles.visualConnector}><ArrowDown aria-hidden="true" /></div>
      <div className={styles.visualNode}>E-Order / E-Invoice Processing</div>
      <div className={styles.visualConnector}><ArrowDown aria-hidden="true" /></div>
      <div className={styles.visualEndpoints}><span>Government</span><span>Peppol</span><span>Trading Partner</span></div>
      <div className={styles.visualFooter}><Blocks aria-hidden="true" /><span>Monitoring &amp; Analytics</span></div>
    </div>
  );
}

export default function IntegrationTechnology() {
  return (
    <div className={styles.page}>
      <header className={styles.pageHeading}><h1>Technology &amp; Patent</h1><span>SAP EDI &amp; eInvoicing Integration Technology</span></header>
      <nav aria-label="Technology sections" className={styles.sectionNav}>
        {sections.map(([id, label]) => <a key={id} href={'#' + id}>{label}</a>)}
      </nav>

      <section id="home" className={styles.hero} aria-labelledby="technology-introduction">
        <div className={styles.heroGrid}>
          <div>
            <p className={styles.eyebrow}>PROPRIETARY SAP INTEGRATION TECHNOLOGY</p>
            <h2 id="technology-introduction">Connecting Global SAP Processes with Electronic Transactions</h2>
            <p className={styles.patentSubheading}>{patentTitle}</p>
            <p className={styles.heroDescription}>The technology provides an integrated architecture for processing SAP-standard business data and electronic transaction documents across enterprise environments.</p>
            <div className={styles.actions}><a className={styles.primaryButton} href="#technology">Explore the Technology</a><a className={styles.secondaryButton} href="#patent">Patent Information</a></div>
            <div className={styles.heroMeta}><span>Inventor: <strong>Arnd Dixit</strong></span><span>U.S. Application: <strong>18/673,332</strong></span></div>
          </div>
          <ArchitectureVisual />
        </div>
        <p className={styles.heroFootnote}>U.S. Patent Application 18/673,332 · Allowed by USPTO; pending issuance</p>
      </section>

      <section id="solutions" className={styles.section} aria-labelledby="solutions-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Solutions</p><h2 id="solutions-heading">SAP EDI &amp; eInvoicing Integration Technology</h2></div>
        <div className={styles.solutions}>{solutions.map(title => <article key={title} className={styles.solution}><Layers3 aria-hidden="true" /><h3>{title}</h3></article>)}</div>
      </section>

      <section id="technology" className={styles.section} aria-labelledby="architecture-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Proprietary SAP E-Order &amp; E-Invoice Integration</p><h2 id="architecture-heading">From SAP Business Data to Electronic Transactions</h2></div>
        <figure className={styles.architecturePanel}>
          <ol className={styles.architecture} aria-label="Eight-stage integration architecture">
            {architecture.map((stage, index) => <li key={stage} className={styles.stage}>
              <div className={index === 2 ? styles.stageAccent : index === 7 ? styles.stageDark : undefined}><span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span><strong>{stage}</strong></div>
              {index < architecture.length - 1 && <ArrowDown className={styles.stageConnector} aria-hidden="true" />}
            </li>)}
          </ol>
          <figcaption className={styles.architectureCaption}><strong>One global SAP architecture</strong> — multiple countries, formats and regulatory environments.</figcaption>
        </figure>
        <div className={styles.overview}>
          <h3>A Technology Foundation for Global SAP Environments</h3>
          <div>
            <p>It addresses the connection between SAP business processes and external e-order/e-invoice ecosystems through data processing, validation, automated error handling, document creation, transmission and monitoring.</p>
            <div className={styles.processes}>{['Data processing', 'Validation', 'Automated exception handling', 'Document creation', 'Transmission', 'Monitoring'].map(process => <span key={process}>{process}</span>)}</div>
            <p>The architecture is designed for enterprise SAP environments where a common global template must support multiple countries, legal entities, transaction formats and regulatory requirements.</p>
          </div>
        </div>
      </section>

      <section id="capabilities" className={styles.section} aria-labelledby="capabilities-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Integration capabilities</p><h2 id="capabilities-heading">Key Capabilities</h2></div>
        <div className={styles.capabilities}>{capabilities.map(({ icon: Icon, title, description }) => <article key={title} className={styles.capability}><Icon aria-hidden="true" /><h3>{title}</h3><p>{description}</p></article>)}</div>
      </section>

      <section id="patent" className={styles.patentSection} aria-labelledby="patent-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Patent &amp; Intellectual Property</p><h2 id="patent-heading">Protected Technology</h2></div>
        <div className={styles.patentGrid}>
          <div className={styles.document}>
            <div className={styles.documentHeader}><span className={styles.eyebrow}>U.S. Patent Application</span><ShieldCheck aria-hidden="true" /></div>
            <h3>{patentTitle}</h3>
            <p className={styles.applicationNumber}>18/673,332</p><p className={styles.documentType}>United States Patent and Trademark Office</p>
            <p className={styles.documentStatus}>Allowed by USPTO; pending issuance</p>
          </div>
          <div>
            <dl className={styles.patentDetails}>
              {[
                ['Inventor', 'Arnd Dixit'],
                ['Assignee/Owner', '[exact legal owner — this should match the patent records]'],
                ['U.S. Patent Application', '18/673,332'],
                ['Filing Date', 'May 24, 2024'],
                ['Status', 'Allowed by USPTO; pending issuance'],
                ['Patent Office', 'United States Patent and Trademark Office'],
                ['Patent Number', 'Pending Issuance'],
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
            <a className={styles.lightButton + ' ' + styles.filingButton} href="https://patentcenter.uspto.gov/applications/18673332" target="_blank" rel="noopener noreferrer">View USPTO Filing</a>
          </div>
        </div>
        <p className={styles.patentStatement}>The patented architecture addresses SAP-standard integration, electronic transaction processing, validation, automated exception handling and monitoring.</p>
      </section>

      <section id="evolution" className={styles.section} aria-labelledby="evolution-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Technology evolution</p><h2 id="evolution-heading">From SAP Integration to Protected Technology</h2></div>
        <ol className={styles.timeline} aria-label="Technology development timeline">
          {milestones.map(([date, title, description]) => <li key={title} className={styles.milestone}><span className={styles.milestoneDate}>{date || '\u00a0'}</span><h3>{title}</h3><p>{description}</p></li>)}
        </ol>
      </section>

      <section id="why-it-matters" className={styles.section} aria-labelledby="benefits-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Why It Matters</p><h2 id="benefits-heading">Designed for Global SAP Enterprises</h2></div>
        <div className={styles.benefits}>{benefits.map(([audience, title, description]) => <article key={title} className={styles.benefit}><p className={styles.eyebrow}>{audience}</p><h3>{title}</h3><p>{description}</p></article>)}</div>
      </section>

      <section id="licensing" className={styles.section} aria-labelledby="licensing-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Technology Licensing</p><h2 id="licensing-heading">Technology Licensing &amp; Strategic Partnerships</h2><p>The technology is available for discussion with organizations seeking enterprise-grade SAP integration and electronic transaction capabilities.</p></div>
        <div className={styles.partners}>{partners.map(({ icon: Icon, title }) => <article key={title} className={styles.partner}><Icon aria-hidden="true" /><h3>{title}</h3></article>)}</div>
        <div id="licensing-options" className={styles.licensingModels}><h3>Potential Licensing Models</h3><div className={styles.modelTags}>{licensingModels.map(model => <span key={model}>{model}</span>)}</div></div>
        <div className={styles.actions}><a className={styles.lightButton} href="#licensing-options">Discuss Licensing</a></div>
      </section>

      <section id="case-studies" className={styles.section} aria-labelledby="cases-heading">
        <div className={styles.sectionHead}><p className={styles.eyebrow}>Case Studies / Implementations</p><h2 id="cases-heading">Enterprise Experience</h2></div>
        <div className={styles.cases}>{['Swiss Krono', 'Nolte GmbH', 'HR Path France'].map(name => <article key={name} className={styles.case}><h3>{name}</h3></article>)}</div>
        <p className={styles.caseNote}>Additional implementation details available upon request.</p>
      </section>

      <section className={styles.finalCta} aria-labelledby="partnership-heading"><h2 id="partnership-heading">Build on a Global SAP Integration Architecture</h2><p>Explore technology partnerships, enterprise licensing and integration opportunities.</p><div className={styles.actions}><a className={styles.primaryButton} href="#licensing">Discuss Technology</a><a className={styles.secondaryButton} href="#patent">Patent Information</a></div></section>
      <p className={styles.footLabel}>Technology &amp; Patent · U.S. Patent Application 18/673,332</p>
    </div>
  );
}