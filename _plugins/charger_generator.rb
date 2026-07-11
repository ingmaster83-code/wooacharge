require 'json'

module Jekyll
  class ChargerPageGenerator < Generator
    safe true
    priority :normal

    def generate(site)
      stations = site.data['stations'] || load_json(site, '_rawdata/stations.json')
      regions  = site.data['regions']  || load_json(site, '_data/regions.json')

      return if stations.empty?

      Jekyll.logger.info "ChargerGenerator:", "#{stations.size}개 충전소 페이지 생성 중..."

      # 충전소 상세 페이지
      stations.each do |st|
        next if st['slug'].to_s.strip.empty?
        site.pages << ChargerPage.new(site, st, regions)
      end

      # 지역별 인덱스 구성
      sido_map = {}
      stations.each do |st|
        sido = st['sido']
        sg   = st['sigungu']
        sido_map[sido] ||= {}
        sido_map[sido][sg] ||= []
        sido_map[sido][sg] << st
      end

      regions.each do |region|
        sido      = region['sido']
        sido_slug = region['slug'] || sido
        sido_stations = stations.select { |s| s['sido'] == sido }
        site.pages << RegionSidoPage.new(site, sido, sido_slug, region['sigungu'], sido_stations)

        region['sigungu'].each do |sg_entry|
          sg_name = sg_entry['name']
          sg_slug = sg_entry['slug'] || sg_name
          sg_stations = (sido_map[sido] || {})[sg_name] || []
          site.pages << RegionSigunguPage.new(site, sido, sido_slug, sg_name, sg_slug, sg_stations)
        end
      end

      site.pages << SearchIndexPage.new(site, stations)

      Jekyll.logger.info "ChargerGenerator:", "완료 (충전소 #{stations.size}개)"
    end

    private

    def load_json(site, path)
      file = File.join(site.source, path)
      return [] unless File.exist?(file)
      JSON.parse(File.read(file, encoding: 'utf-8'))
    rescue => e
      Jekyll.logger.warn "ChargerGenerator:", "#{path} 로드 실패: #{e.message}"
      []
    end
  end

  # 리스트 페이지용 요약 필드 계산 (급속/완속 대수, 사용가능 대수)
  def self.summarize(station)
    chargers = station['chargers'] || []
    {
      'slug'             => station['slug'],
      'name'             => station['name'],
      'address'          => station['address'],
      'floor'            => station['floor'],
      'parking_free'     => station['parking_free'],
      'fast_count'       => chargers.count { |c| c['speed'] == '급속' },
      'slow_count'       => chargers.count { |c| c['speed'] == '완속' },
      'available_count'  => chargers.count { |c| c['status_class'] == 'avail' },
    }
  end

  class ChargerPage < Page
    def initialize(site, st, regions)
      @site = site
      @base = site.source
      @dir  = "charger/#{st['slug']}"
      @name = 'index.html'

      self.process(@name)
      self.read_yaml(File.join(@base, '_layouts'), 'charger.html')

      sido_region = regions.find { |r| r['sido'] == st['sido'] } || {}
      sg_entry    = (sido_region['sigungu'] || []).find { |s| s['name'] == st['sigungu'] } || {}

      chargers = (st['chargers'] || []).map do |c|
        {
          'speed'        => c['speed'],
          'capacity'     => c['capacity'],
          'status_text'  => c['status_text'],
          'status_class' => c['status_class'],
        }
      end
      available = chargers.count { |c| c['status_class'] == 'avail' }

      self.data['layout']       = 'charger'
      self.data['station_name'] = st['name']
      self.data['sido']         = st['sido']
      self.data['sido_slug']    = sido_region['slug'] || st['sido']
      self.data['sigungu']      = st['sigungu']
      self.data['sigungu_slug'] = sg_entry['slug'] || st['sigungu']
      self.data['address']      = st['address']
      self.data['floor']        = st['floor']
      self.data['operator']     = st['operator']
      self.data['tel']          = st['tel']
      self.data['hours']        = st['hours']
      self.data['parking_free'] = st['parking_free']
      self.data['restricted']   = st['restricted']
      self.data['lat']          = st['lat']
      self.data['lon']          = st['lon']
      self.data['chargers']     = chargers
      self.data['last_updated'] = st['last_updated']
      self.data['title']        = "#{st['name']} 충전소 위치 충전기현황"
      self.data['description']  = build_desc(st, available, chargers.size)
    end

    private

    def build_desc(st, available, total)
      return st['seo_description'] if st['seo_description'].to_s.length > 10
      loc = "#{st['sido']} #{st['sigungu']}"
      "#{loc} #{st['name']} 전기차 충전소 위치, 충전기 #{total}대(사용가능 #{available}대) 실시간 현황을 확인하세요."[0, 155]
    end
  end

  class RegionSidoPage < Page
    def initialize(site, sido, sido_slug, sigungu_list, stations)
      @site = site
      @base = site.source
      @dir  = "region/#{sido_slug}"
      @name = 'index.html'

      self.process(@name)
      self.read_yaml(File.join(@base, '_layouts'), 'region.html')
      self.data['layout']        = 'region'
      self.data['sido']          = sido
      self.data['sido_slug']     = sido_slug
      self.data['sigungu']       = nil
      self.data['charger_count'] = stations.size
      self.data['sigungu_list']  = sigungu_list
      self.data['chargers']      = stations.first(30).map { |s| Jekyll.summarize(s) }
      self.data['title']         = "#{sido} 전기차 충전소 목록"
      self.data['description']   = "#{sido} 전체 전기차 충전소 #{stations.size}개 위치, 급속/완속 현황."
    end
  end

  class RegionSigunguPage < Page
    def initialize(site, sido, sido_slug, sigungu, sg_slug, stations)
      @site = site
      @base = site.source
      @dir  = "region/#{sido_slug}/#{sg_slug}"
      @name = 'index.html'

      self.process(@name)
      self.read_yaml(File.join(@base, '_layouts'), 'region.html')
      self.data['layout']        = 'region'
      self.data['sido']          = sido
      self.data['sido_slug']     = sido_slug
      self.data['sigungu']       = sigungu
      self.data['sg_slug']       = sg_slug
      self.data['charger_count'] = stations.size
      self.data['chargers']      = stations.map { |s| Jekyll.summarize(s) }
      self.data['title']         = "#{sido} #{sigungu} 전기차 충전소 목록"
      self.data['description']   = "#{sido} #{sigungu} 전기차 충전소 #{stations.size}개 위치, 급속/완속 현황."
    end
  end

  class SearchIndexPage < Page
    def initialize(site, stations)
      @site = site
      @base = site.source
      @dir  = ''
      @name = 'search_index.json'

      self.process(@name)
      self.data = { 'layout' => nil, 'sitemap' => false }

      index = stations.map do |s|
        {
          'slug'    => s['slug'],
          'name'    => s['name'],
          'sido'    => s['sido'],
          'sigungu' => s['sigungu'],
          'address' => s['address'],
          'lat'     => s['lat'],
          'lon'     => s['lon'],
          'fast_count' => (s['chargers'] || []).count { |c| c['speed'] == '급속' },
          'slow_count' => (s['chargers'] || []).count { |c| c['speed'] == '완속' },
          'available_count' => (s['chargers'] || []).count { |c| c['status_class'] == 'avail' },
        }
      end

      self.content = index.to_json
    end

    def output = self.content
    def render(layouts, registers); end
  end
end
