/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Callout, Code, Formula, Table, Term } from '../primitives';

export function Features() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Feature engineering</h1>
      <p className="docs-article__lede">
        Twenty-two raw variables become 136 features for the bloom model and 40 for the habitat
        model. This chapter explains every family of them — the geometry features that encode
        ocean physics, the temporal features that encode history, and the problem-specific ones
        that encode biology — and why each was worth computing.
      </p>

      <h2 id="principle">The organising principle</h2>
      <p>
        A raw measurement answers "what is the value here, now". Almost every question worth
        asking is comparative:
      </p>
      <ul>
        <li>Is this value unusual <em>for this place, in this season</em>? → anomaly features</li>
        <li>Where is it heading? → difference and rolling features</li>
        <li>What happened upstream in time? → lag features</li>
        <li>Is there a boundary here? → gradient features</li>
        <li>Is the water rotating or being pulled apart? → eddy features</li>
        <li>Is deep, nutrient-rich water being pushed up? → upwelling features</li>
      </ul>
      <p>
        Everything below is one of those six shapes. And every single one of them is{' '}
        <strong>backward-looking by construction</strong> — the only forward shift anywhere in
        the codebase is the target itself.
      </p>

      <hr />

      <h2 id="geometry">Shared: spatial geometry features</h2>
      <p>
        These live in <code>marine_ml/features/geometry.py</code> and are used by both problems.
        They are computed on the regular grid, so spacing is in degrees — and where a physical
        unit matters the conversion to metres is applied explicitly.
      </p>

      <Callout kind="note" title="One detail that would have biased every east–west gradient">
        <p>
          A degree of longitude gets shorter as you move away from the equator. At 20°N it is
          about 6% shorter than at the equator. Every horizontal gradient is therefore divided by{' '}
          <code>111,320 · cos(latitude)</code> in the east–west direction and by a constant
          111,320 in the north–south direction. Skip this and every zonal gradient in the domain
          is systematically wrong, in a way that grows with latitude.
        </p>
      </Callout>

      <h3>Fronts — <code>gradient_magnitude</code></h3>
      <Callout kind="jargon" title="Jargon buster — a front">
        <p>
          An ocean <Term>front</Term> is a boundary where two water masses meet, showing up as a
          sharp horizontal change in temperature, salinity or colour over a short distance.
          Fronts matter because they physically concentrate things: nutrients get pushed up along
          them, plankton accumulate, small fish come to eat the plankton, and big fish come to eat
          the small fish. INCOIS's operational PFZ advisory is, at heart, a hand-tuned SST front
          detector — these features are the learned version of the same signal.
        </p>
      </Callout>
      <Formula
        expr={'|∇T| = √( (∂T/∂y / 111320)²  +  (∂T/∂x / (111320·cos φ))² )'}
        where="T is the field (temperature or log-chlorophyll), φ is latitude. A centred difference stands in for the Sobel operator: on a smooth geophysical field at this resolution the two agree closely, and it handles irregular edges and the NaN land mask without padding gymnastics."
      />

      <h3>Eddies — <code>okubo_weiss</code> and <code>relative_vorticity</code></h3>
      <Callout kind="jargon" title="Jargon buster — mesoscale eddies">
        <p>
          The ocean is full of rotating vortices tens to hundreds of kilometres across, called{' '}
          <Term>mesoscale eddies</Term>. They trap water — and whatever is in it — and carry it
          for weeks. Cyclonic eddies pull deep nutrient-rich water up in their centres, making
          them productive; many pelagic species aggregate around eddy <em>edges</em> rather than
          their centres.
        </p>
      </Callout>
      <p>
        The <Term>Okubo–Weiss parameter</Term> separates rotation-dominated flow from
        strain-dominated flow:
      </p>
      <Formula
        expr={'W = Sₙ² + Sₛ² − ω²\n\nSₙ = ∂u/∂x − ∂v/∂y     (normal strain)\nSₛ = ∂v/∂x + ∂u/∂y     (shear strain)\nω  = ∂v/∂x − ∂u/∂y     (relative vorticity)'}
        where="W is negative where rotation beats strain — that is an eddy interior. W is positive in the stretched filaments between eddies. Units are s⁻²."
      />
      <p>
        <code>relative_vorticity</code> keeps the sign separately, because in the northern
        hemisphere positive means cyclonic and negative anticyclonic, and those are ecologically
        different. <code>eddy_kinetic_energy</code> is computed against the time-mean flow at each
        cell, so a persistent boundary current does not falsely read as eddy activity.
      </p>

      <h3>Upwelling — the mechanism behind blooms</h3>
      <Callout kind="jargon" title="Jargon buster — Ekman transport and upwelling">
        <p>
          Wind blowing over the sea does not push the surface water in the direction it blows. The
          Earth's rotation deflects it — to the right in the northern hemisphere. Net water
          transport in the wind-driven surface layer ends up at 90° to the wind. This is{' '}
          <Term>Ekman transport</Term>.
        </p>
        <p>
          When that transport pushes water <em>away</em> from a coast, water must come from
          somewhere to replace it, and it comes from below: cold, dark, nutrient-rich deep water
          rises into the sunlit layer. That is <Term>coastal upwelling</Term>, and it is why the
          world's most productive fisheries sit on upwelling coasts. It is also the nutrient
          injection that precedes many harmful blooms.
        </p>
      </Callout>

      <p>Two physically distinct mechanisms are captured, and the Arabian Sea needs both:</p>

      <h4>Coastal: the Bakun upwelling index</h4>
      <Formula
        expr={'UI = τ_alongshore / (ρ_sw · f)\n\nτ_alongshore = τₓ·sin θ + τ_y·cos θ\nf = 2Ω·sin(latitude)          (Coriolis parameter)'}
        where="ρ_sw = 1025 kg/m³, Ω = 7.2921×10⁻⁵ rad/s, θ is coastline orientation (0° = north–south, a fair approximation for India's west coast). Units are m³/s per metre of coastline; positive means offshore transport, i.e. upwelling-favourable."
      />
      <p>
        The Coriolis parameter goes to zero at the equator, which would make the index infinite
        there. A ±2° band around the equator is masked to NaN rather than emitting an infinity
        that would poison the feature everywhere downstream.
      </p>

      <h4>Open ocean: Ekman pumping</h4>
      <Formula
        expr={'w_Ekman = curl(τ) / (ρ_sw · f)'}
        where="Positive wind stress curl in the northern hemisphere drives surface divergence and upwells nutrient-rich water; negative curl downwells. Units are m/s."
      />
      <p>
        This matters specifically here: the <Term>Findlater Jet</Term>, the low-level monsoon wind
        jet over the Arabian Sea, has strong curl that drives a large open-ocean upwelling region
        well offshore of the coastal band. Blooms out there are not explained by the coastal index
        at all. Both features are needed, and the model uses them differently.
      </p>

      <h3>Distance to coast</h3>
      <p>
        Great-circle distance from each ocean cell to the nearest land cell, in km. Computed by
        brute-force nearest-neighbour on the unit sphere with a KD-tree — chord distance in 3D
        orders identically to great-circle distance, so the nearest neighbour found is the correct
        one, and the chord is then converted back to arc length. At these grid sizes (10⁴–10⁵
        cells) that is fast enough and avoids pulling in a geospatial dependency for one feature.
      </p>

      <hr />

      <h2 id="temporal">Shared: temporal features</h2>
      <p>
        These live in <code>marine_ml/features/temporal.py</code>. The single most important
        property of the whole module: <strong>nothing here may look forward in time</strong>. For
        a row at time <em>t</em>, every value computed depended only on data available at or
        before <em>t</em>.
      </p>

      <h3>Climatology and anomalies</h3>
      <Callout kind="jargon" title="Jargon buster — climatology">
        <p>
          A <Term>climatology</Term> is the long-run average condition: "what does this grid cell
          normally look like in August". An <Term>anomaly</Term> is today's value minus that
          normal. A <Term>standardised anomaly</Term> (or z-anomaly) divides the anomaly by the
          local standard deviation, giving "how many typical wobbles away from normal is this" —
          a number that is comparable between a calm open-ocean cell and a wildly variable coastal
          one.
        </p>
      </Callout>
      <p>
        For each cell and each calendar month we compute the mean and standard deviation of
        chlorophyll and temperature, then derive:
      </p>
      <Formula
        expr={'x_anomaly  = x − mean(cell, month)\nx_zanomaly = x_anomaly / std(cell, month)'}
        where="A zero or absent standard deviation (a cell observed once in training) would produce infinity, so it is replaced with NaN rather than divided through."
      />
      <p>
        The z-form is what makes a threshold comparable across regimes, and it is exactly why a
        single global chlorophyll cutoff was rejected as a bloom definition. Monthly is the right
        granularity here: a per-day-of-year mean over a handful of years is mostly noise.
      </p>
      <Callout kind="warn" title="This is fitted on training rows only">
        <p>
          <code>fit_climatology</code> and <code>apply_climatology</code> are two separate
          functions specifically so that fitting on the wrong rows takes deliberate effort. A
          climatology fitted over the full record leaks the test period's own mean into training
          features.
        </p>
      </Callout>

      <h3>Lags</h3>
      <p>
        <code>{'{column}_lag{n}'}</code> — the value <em>n</em> days ago, per cell. HAB uses lags
        of 3, 7, 14 and 30 days on chlorophyll, temperature, all three nutrients, primary
        production, mixed layer depth, both upwelling indices and wind stress magnitude.
      </p>
      <p>
        The shift is done on the <strong>date</strong>, not on row position. A gap in a cell's
        time series produces NaN rather than silently pulling in whatever record happens to sit
        adjacent in the table — which is a genuine and very quiet source of wrong features.
      </p>
      <p>
        Lagging the upwelling indices is the entire point of having wind at all: nutrient
        injection precedes the bloom it feeds by days to weeks, so the concurrent value is asking
        the wrong question.
      </p>

      <h3>Rolling statistics</h3>
      <p>
        Trailing mean and standard deviation over 7-, 14- and 30-day windows, for chlorophyll,
        temperature, current speed, both upwelling indices and wind speed.
      </p>
      <Code>{`shifted = grouped[column].shift(1)          # exclude today
roller  = shifted.rolling(steps, min_periods=max(2, steps // 2))
frame[f"{column}_roll{window}_mean"] = roller.mean()`}</Code>
      <p>
        The <code>shift(1)</code> before rolling is what makes the window strictly trailing. A
        rolling window centred on <em>t</em>, or one that includes <em>t</em>, is one of the most
        common ways a time-series model quietly cheats.
      </p>

      <h3>Differences — rate of change</h3>
      <p>
        <code>{'{column}_delta'}</code> (first difference) and <code>{'{column}_accel'}</code>{' '}
        (second difference), for chlorophyll and temperature. A bloom is a trajectory, not a
        level: chlorophyll climbing steeply off a low base is a developing bloom; the same value
        while flat is not.
      </p>

      <h3>Cyclical time encoding</h3>
      <p>
        Feeding the model "day 365" and "day 1" as raw integers puts an artificial cliff between
        31 December and 1 January — exactly the wrong inductive bias for a strongly seasonal
        system. So day-of-year and month are encoded as sine/cosine pairs, which wrap smoothly:
      </p>
      <Formula
        expr={'doy_sin = sin(2π · dayofyear / 366)\ndoy_cos = cos(2π · dayofyear / 366)\nmonth_sin = sin(2π · (month−1) / 12)\nmonth_cos = cos(2π · (month−1) / 12)'}
        where="366 rather than 365 keeps leap years on the same circle instead of overshooting 2π."
      />

      <h3>Monsoon phase</h3>
      <p>
        A categorical feature, because the northern Indian Ocean's productivity cycle is
        monsoon-driven and its phases are <em>qualitatively</em> different states, not points on a
        smooth curve:
      </p>
      <Table
        headers={['Phase', 'Months', 'Regime']}
        rows={[
          ['southwest_monsoon', 'Jun–Sep', 'Strong upwelling-favourable winds; the main bloom season.'],
          ['post_monsoon', 'Oct–Nov', 'Winds relax, stratification rebuilds.'],
          ['northeast_monsoon', 'Dec–Feb', 'Convective mixing brings nutrients up from below — a different mechanism entirely.'],
          ['pre_monsoon', 'Mar–May', 'Warm, stratified, generally low productivity.'],
        ]}
      />

      <hr />

      <h2 id="hab-features">Problem A: HAB-specific features</h2>

      <h3>Nutrient ratios</h3>
      <Callout kind="jargon" title="Jargon buster — the Redfield ratio">
        <p>
          Marine plankton have a remarkably consistent elemental composition, roughly 106 carbon
          : 16 nitrogen : 1 phosphorus — the <Term>Redfield ratio</Term>. Departures from it tell
          you which nutrient is limiting growth, and therefore which kind of plankton is
          favoured.
        </p>
      </Callout>
      <p>We compute N:P and N:Si, plus their departures from Redfield stoichiometry:</p>
      <Formula
        expr={'n_to_p          = no3 / po4\nn_to_p_anomaly  = n_to_p − 16\nn_to_si         = no3 / si\nn_to_si_anomaly = n_to_si − 1'}
        where="Both denominators are guarded (values ≤ 1e-6 become NaN). Phosphate goes to near-zero in depleted surface water, and an unguarded ratio would produce infinities exactly where the signal is most interesting."
      />
      <p>
        The N:Si ratio carries information the raw concentrations do not: diatoms need silicate to
        build their shells, flagellates do not. Silicate depletion relative to nitrogen shifts the
        competitive advantage from diatoms toward the flagellates that dominate harmful blooms.
      </p>

      <h3>Stratification</h3>
      <Callout kind="jargon" title="Jargon buster — stratification and the mixed layer">
        <p>
          The <Term>mixed layer</Term> is the surface layer that wind and waves keep well stirred,
          so it has near-uniform temperature and density. Below it, water is denser and does not
          readily mix upward. When the mixed layer is shallow the water column is strongly{' '}
          <Term>stratified</Term>.
        </p>
        <p>
          For a bloom this is decisive. Phytoplankton need light, which only exists near the
          surface. A shallow mixed layer keeps them there; a deep one keeps mixing them down into
          the dark where they cannot grow.
        </p>
      </Callout>
      <Formula
        expr={'stratification_index = 1 / (1 + mlotst)\nlog_mld             = log(1 + mlotst)\nwarm_shallow_index  = thetao / (1 + mlotst)'}
        where="warm_shallow_index is an interaction term: warm water over a shallow mixed layer is the strongest bloom-retention signal, and neither term expresses it alone."
      />

      <h3>Upwelling interactions</h3>
      <ul>
        <li>
          <code>upwelling_x_stratification</code> — upwelling only injects nutrients into the
          sunlit zone where the water column is shallow enough for the pumped water to reach it,
          so the interaction carries more signal than either term alone.
        </li>
        <li>
          <code>upwelling_favourable</code> — the index clipped at zero. Downwelling is a
          different regime rather than "negative upwelling", and separating them lets the model
          treat them as such.
        </li>
      </ul>

      <h3>Marine heatwave flag</h3>
      <p>
        Following the Hobday definition: sea surface temperature above the local seasonal 90th
        percentile for at least <strong>5 consecutive days</strong>. The duration requirement is
        the part that matters — a single warm day is weather; five consecutive is an event with
        ecological consequences.
      </p>
      <p>
        Implemented in standardised-anomaly space, which keeps the threshold local and seasonal
        without fitting a separate percentile surface: the z-score cutting off the 90th percentile
        of a standard normal is 1.2816. Run lengths are computed per cell with a cumulative-count
        trick, and both the binary flag and the current <code>hot_run_length</code> are kept.
      </p>

      <h3>What gets excluded from the HAB model's inputs</h3>
      <Table
        headers={['Excluded', 'Why']}
        rows={[
          [<code>bloom_t3 / bloom_t5 / bloom_t7</code>, 'These are the answers.'],
          [<code>chl_t3 / chl_t5 / chl_t7</code>, 'Future chlorophyll — the quantity being forecast.'],
          [<code>threshold_t*</code>, 'The future threshold used to build the label.'],
          [
            <>
              <code>threshold</code>, <code>bloom_exceedance</code>
            </>,
            'Derived from the label definition itself.',
          ],
          [
            <>
              <code>latitude</code>, <code>longitude</code>, <code>date</code>,{' '}
              <code>season</code>, <code>region</code>
            </>,
            'Raw identifiers, not physics.',
          ],
        ]}
      />
      <p>
        Note what stays <em>in</em>: <code>chl</code> itself and <code>is_bloom</code> at time{' '}
        <em>t</em>. The current chlorophyll level is legitimate input to forecasting the future
        level, and whether it is blooming <em>now</em> is fair game as a feature — it is
        blooming at <em>t+h</em> that is the answer. But <code>threshold</code> and{' '}
        <code>bloom_exceedance</code> are derived from the label definition, so they go.
      </p>

      <hr />

      <h2 id="habitat-features">Problem B: habitat-specific features</h2>

      <h3>Prey-availability lag</h3>
      <p>
        Chlorophyll 30 and 60 days earlier, not concurrent. A phytoplankton bloom takes weeks to
        propagate up the food chain to anything a fishing vessel would target — asking "is there
        chlorophyll here today" is the wrong question.
      </p>
      <p>
        Implemented by <em>re-sampling the same fields at a shifted date</em> rather than by
        shifting rows, because these are scattered points with irregular dates and there is no
        per-cell time series to shift along. <code>chl_trend_30d</code> (current minus 30-day-ago)
        captures whether the prey base was building or collapsing, not just its level.
      </p>

      <h3>Thermal niche</h3>
      <p>
        Every species has a temperature range it is actually found in. We fit that range{' '}
        <strong>per species, from training presences only</strong>, and then place each row's
        local temperature within it:
      </p>
      <Formula
        expr={'thermal_low     = 5th percentile of temperature at this species\' presences\nthermal_high    = 95th percentile\nthermal_optimum = median\n\nthermal_position = (T − thermal_low) / (thermal_high − thermal_low)\nthermal_distance = |T − thermal_optimum|\nin_thermal_range = thermal_low ≤ T ≤ thermal_high'}
        where="thermal_position outside 0–1 means the location is outside the species' observed thermal range. The niche is refitted inside every cross-validation fold — fitting it once outside the loop would leak held-out temperatures into a training feature."
      />

      <h3>Bathymetric context</h3>
      <p>
        Depth spans four orders of magnitude and its ecological effect is strongly non-linear near
        the shelf break, so depth enters three ways: raw, as <code>log_depth</code>, and as a
        categorical bucket a linear baseline could never discover on its own.
      </p>
      <Table
        headers={['Bucket', 'Depth range']}
        rows={[
          ['nearshore', '< 50 m'],
          ['shelf', '50 – 200 m'],
          ['slope', '200 – 1,000 m'],
          ['deep', '1,000 – 3,000 m'],
          ['abyssal', '> 3,000 m'],
        ]}
      />

      <h3>Species identity as a feature</h3>
      <p>
        <code>species_key</code> is a categorical input, one-hot encoded. That is what makes this
        one model rather than five, and it is the tabular analogue of a shared encoder with
        species-specific output heads — species with few records borrow strength from the shared
        environmental response.
      </p>

      <Callout kind="warn" title="Latitude and longitude are deliberately excluded">
        <p>
          With spatially clustered presences, a tree model will happily memorise "presence lives
          at 12.3°N, 74.8°E" and score beautifully under random cross-validation while learning no
          ecology whatsoever. Spatial structure has to enter through environment and bathymetry
          instead. This is the difference between a model that has learned where fish live and one
          that has learned a map.
        </p>
      </Callout>

      <Callout kind="lesson" title="A bug worth reading about: the feature list that depended on call order">
        <p>
          The habitat model originally scored much lower (cross-validated TSS 0.66, holdout 0.53).
          The cause: <code>feature_columns()</code> discovered its column list by inspecting the
          table, and it was called <em>before</em> <code>apply_thermal_niche</code> had added the
          thermal columns. Meanwhile <code>species_key</code> sat in the excluded-identifier set.
        </p>
        <p>
          The result was a model with <strong>no species-dependent input at all</strong>. Five
          "species" were one pooled model wearing five labels, and the carefully per-fold-fitted
          thermal niche was computed and then thrown away.
        </p>
        <p>
          It was found by checking whether the exported per-species map tiles actually differed.
          They were byte-identical. The fix was to name those columns explicitly
          (<code>THERMAL_FEATURES</code>, <code>SPECIES_FEATURE</code>) so that the feature list
          cannot depend on the order two functions happen to be called in. Holdout TSS went from
          0.53 to 0.788.
        </p>
      </Callout>
    </>
  );
}
